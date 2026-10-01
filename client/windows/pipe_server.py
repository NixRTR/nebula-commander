"""
Named-pipe API server hosted by the Windows service (service.py) - the
Windows counterpart of client/linux/dbus_server.py. See pipe_protocol.py for
the wire format and command list.

Authorization: every command is READ or MANAGE (the _COMMANDS table below,
same shape as dbus_server._METHODS). READ is open to any local authenticated
caller. MANAGE requires the caller's token to be an *enabled* member of
BUILTIN\\Administrators, i.e. an elevated (UAC "Run as administrator")
process - CheckTokenMembership ignores the deny-only Administrators SID a
filtered, non-elevated admin token carries, so an admin's normal unelevated
app is treated exactly like a standard user's. Remote (SMB) clients are
rejected at the pipe level (PIPE_REJECT_REMOTE_CLIENTS + a deny ACE for
NETWORK logons).

Each connected client is served on its own short-lived thread, so one slow
or stuck client can't block the others or the service.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable

from client import service_api
from client.windows import nebula_install
from client.windows import pipe_protocol as proto
from client.windows.shared_paths import load_status, shared_root

READ = "read"
MANAGE = "manage"

# D:(D;;GA;;;NU) - deny NETWORK logons outright; AU may connect (read/write
# the pipe itself - per-command authorization happens in _handle); SYSTEM and
# Administrators full control.
_PIPE_SDDL = "D:(D;;GA;;;NU)(A;;GRGW;;;AU)(A;;GA;;;SY)(A;;GA;;;BA)"
_MAX_INSTANCES = 16
_FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000


class _BadRequest(Exception):
    pass


def _winerror(e: BaseException) -> "int | None":
    """Win32 error code of a pywin32 error. Matched by attribute, never by
    `except pywintypes.error`: in the PyInstaller-frozen service that class
    check silently fails to match (a second pywintypes module object), which
    let an expected error escape and kill the pipe thread - found on a real
    Win11 install (pipe-squatting test), not reproducible from source."""
    return getattr(e, "winerror", None)


def _arg(args: dict, name: str, typ: type, *, required: bool = True, default: Any = None) -> Any:
    value = args.get(name, default)
    if value is None:
        if required:
            raise _BadRequest(f"missing argument {name!r}")
        return None
    if not isinstance(value, typ) or (typ is int and isinstance(value, bool)):
        raise _BadRequest(f"argument {name!r} must be {typ.__name__}")
    return value


class ServiceHooks:
    """What the pipe server needs from the running service (implemented by
    service.NebulaCommanderService)."""

    def restart_poll(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def update_nebula(self, tag: "str | None") -> str:  # pragma: no cover - interface
        raise NotImplementedError


def _build_commands(hooks: ServiceHooks) -> "dict[str, tuple[Callable[[dict], Any], str]]":
    out_dir = shared_root()

    def get_status(_a):
        return load_status()

    def get_settings(_a):
        s = service_api.get_settings()
        return {k: s.get(k) for k in (
            "server", "interval", "accept_dns", "node_id", "accepted_subnet_routes", "accepted_exit_node",
        )}

    def is_enrolled(_a):
        enrolled, server = service_api.is_enrolled()
        return {"enrolled": enrolled, "server": server}

    def get_dns_configured(_a):
        import os
        return os.path.isfile(os.path.join(out_dir, "dns-client.json"))

    def set_settings(a):
        partial = {}
        if "server" in a:
            partial["server"] = _arg(a, "server", str).strip()
        if "interval" in a:
            partial["interval"] = max(10, min(3600, _arg(a, "interval", int)))
        if "accept_dns" in a:
            partial["accept_dns"] = _arg(a, "accept_dns", bool)
        service_api.set_settings(partial)
        hooks.restart_poll()
        return None

    def enroll(a):
        node_id = service_api.enroll(_arg(a, "server", str), _arg(a, "code", str))
        hooks.restart_poll()
        return {"node_id": node_id}

    def accept_route(a):
        cidr, via = service_api.accept_route(out_dir, _arg(a, "cidr", str), _arg(a, "via", str, required=False))
        hooks.restart_poll()
        return {"cidr": cidr, "via": via}

    def reject_route(a):
        service_api.reject_route(out_dir, _arg(a, "cidr", str))
        hooks.restart_poll()
        return None

    def accept_exit_node(a):
        service_api.accept_exit_node(out_dir, _arg(a, "via", str))
        hooks.restart_poll()
        return None

    def reject_exit_node(_a):
        service_api.reject_exit_node(out_dir)
        hooks.restart_poll()
        return None

    def update_nebula(a):
        return {"tag": hooks.update_nebula(_arg(a, "tag", str, required=False))}

    def poll_now(_a):
        hooks.restart_poll()
        return None

    return {
        proto.CMD_GET_STATUS: (get_status, READ),
        proto.CMD_GET_SETTINGS: (get_settings, READ),
        proto.CMD_IS_ENROLLED: (is_enrolled, READ),
        proto.CMD_GET_AVAILABLE_ROUTES: (lambda _a: service_api.get_available_routes(out_dir), READ),
        proto.CMD_GET_ADVERTISED_ROUTES: (lambda _a: service_api.get_advertised_routes(), READ),
        proto.CMD_GET_CONFIG_YAML: (lambda _a: service_api.get_config_yaml(out_dir), READ),
        proto.CMD_GET_DNS_CONFIGURED: (get_dns_configured, READ),
        proto.CMD_GET_NEBULA_VERSION: (lambda _a: nebula_install.installed_version(), READ),
        proto.CMD_GET_LATEST_NEBULA_TAG: (lambda _a: nebula_install.latest_tag(), READ),
        proto.CMD_SET_SETTINGS: (set_settings, MANAGE),
        proto.CMD_ENROLL: (enroll, MANAGE),
        proto.CMD_ACCEPT_ROUTE: (accept_route, MANAGE),
        proto.CMD_REJECT_ROUTE: (reject_route, MANAGE),
        proto.CMD_ACCEPT_EXIT_NODE: (accept_exit_node, MANAGE),
        proto.CMD_REJECT_EXIT_NODE: (reject_exit_node, MANAGE),
        proto.CMD_UPDATE_NEBULA: (update_nebula, MANAGE),
        proto.CMD_POLL_NOW: (poll_now, MANAGE),
        proto.CMD_RELOAD_SETTINGS: (poll_now, MANAGE),
    }


def _caller_is_elevated_admin(pipe) -> bool:
    """True only if the connected client's token has BUILTIN\\Administrators
    *enabled* (elevated). Must be called after at least one ReadFile on the
    pipe (Windows won't impersonate before the client has written)."""
    import win32api
    import win32security

    admins = win32security.CreateWellKnownSid(win32security.WinBuiltinAdministratorsSid)
    try:
        win32security.ImpersonateNamedPipeClient(pipe)
    except Exception:
        return False
    try:
        token = win32security.OpenThreadToken(
            win32api.GetCurrentThread(), win32security.TOKEN_QUERY, True
        )
        try:
            return bool(win32security.CheckTokenMembership(token, admins))
        finally:
            token.Close()
    except Exception:
        return False
    finally:
        win32security.RevertToSelf()


def _error(code: str, message: str) -> dict:
    return {"ok": False, "code": code, "error": message}


class PipeServer(threading.Thread):
    def __init__(self, hooks: ServiceHooks, stop_event: threading.Event, log: Callable[[str], None]) -> None:
        super().__init__(name="pipe-server", daemon=True)
        self._commands = _build_commands(hooks)
        self._stop_event = stop_event
        self._log = log

    def _security_attributes(self):
        import win32security

        sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
            _PIPE_SDDL, win32security.SDDL_REVISION_1
        )
        sa = win32security.SECURITY_ATTRIBUTES()
        sa.SECURITY_DESCRIPTOR = sd
        return sa

    def run(self) -> None:
        # Never let anything end this loop except stop_event - if this thread
        # dies, the app loses its whole API with no visible error.
        while not self._stop_event.is_set():
            try:
                self._accept_loop()
            except Exception as e:
                self._log(f"Pipe server error, restarting: {e}")
                self._stop_event.wait(5)

    def _accept_loop(self) -> None:
        import win32pipe

        sa = self._security_attributes()
        # The first instance is created with FILE_FLAG_FIRST_PIPE_INSTANCE so
        # that if some other process already owns this pipe name (squatting it
        # to impersonate the service to the GUI), we fail loudly instead of
        # silently sharing the name. Clients additionally verify the server
        # process is this service (see the app's PipeClient.cs).
        first = True
        squat_logged = False  # log a squatting incident once, not every retry
        while not self._stop_event.is_set():
            try:
                pipe = win32pipe.CreateNamedPipe(
                    proto.PIPE_NAME,
                    win32pipe.PIPE_ACCESS_DUPLEX | (_FILE_FLAG_FIRST_PIPE_INSTANCE if first else 0),
                    win32pipe.PIPE_TYPE_MESSAGE
                    | win32pipe.PIPE_READMODE_MESSAGE
                    | win32pipe.PIPE_WAIT
                    | win32pipe.PIPE_REJECT_REMOTE_CLIENTS,
                    _MAX_INSTANCES,
                    proto.BUFFER_SIZE,
                    proto.BUFFER_SIZE,
                    0,
                    sa,
                )
            except Exception as e:
                if first and _winerror(e) == 5:
                    if not squat_logged:
                        self._log(
                            f"{proto.PIPE_NAME} is already owned by another process - possible pipe "
                            "squatting; the control API is unavailable until that process exits."
                        )
                        squat_logged = True
                else:
                    self._log(f"CreateNamedPipe failed: {e}")
                self._stop_event.wait(5)
                continue
            first = False

            try:
                # Blocks until a client connects. The last pending call may
                # outlive SvcStop until the service process exits, which SCM
                # tolerates (daemon thread).
                win32pipe.ConnectNamedPipe(pipe, None)
            except Exception as e:
                # ERROR_PIPE_CONNECTED (535): client connected between Create
                # and Connect - that's a success.
                if _winerror(e) != 535:
                    self._close(pipe)
                    continue
            threading.Thread(target=self._serve_one, args=(pipe,), name="pipe-client", daemon=True).start()

    def _serve_one(self, pipe) -> None:
        import win32file

        try:
            _, data = win32file.ReadFile(pipe, proto.BUFFER_SIZE)
            resp = self._handle(pipe, data)
            win32file.WriteFile(pipe, json.dumps(resp).encode("utf-8"))
            win32file.FlushFileBuffers(pipe)
        except Exception as e:
            # A client that disconnects early (e.g. the app refusing a pipe it
            # doesn't trust) is a Win32 error here - expected, not worth a log.
            if _winerror(e) is None:
                self._log(f"Pipe client handling failed: {e}")
        finally:
            self._close(pipe)

    def _handle(self, pipe, data: bytes) -> dict:
        try:
            msg = json.loads(data.decode("utf-8"))
            if not isinstance(msg, dict):
                raise ValueError("request must be a JSON object")
        except Exception as e:
            return _error(proto.ERR_BAD_REQUEST, f"malformed request: {e}")

        cmd = msg.get("cmd")
        args = msg.get("args") or {}
        entry = self._commands.get(cmd) if isinstance(cmd, str) else None
        if entry is None:
            return _error(proto.ERR_UNKNOWN_COMMAND, f"unknown command: {cmd!r}")
        if not isinstance(args, dict):
            return _error(proto.ERR_BAD_REQUEST, "args must be a JSON object")
        handler, level = entry

        if level == MANAGE and not _caller_is_elevated_admin(pipe):
            return _error(
                proto.ERR_ADMIN_REQUIRED,
                "Administrator required - run the Nebula Commander app as administrator to change settings.",
            )

        try:
            return {"ok": True, "result": handler(args)}
        except _BadRequest as e:
            return _error(proto.ERR_BAD_REQUEST, str(e))
        except service_api.ServiceApiError as e:
            return _error(proto.ERR_FAILED, e.message)
        except nebula_install.NebulaInstallError as e:
            return _error(proto.ERR_FAILED, e.message)
        except Exception as e:
            self._log(f"Pipe command {cmd!r} failed: {e}")
            return _error(proto.ERR_FAILED, str(e))

    @staticmethod
    def _close(pipe) -> None:
        import win32file
        import win32pipe

        try:
            win32pipe.DisconnectNamedPipe(pipe)
        except Exception:
            pass
        try:
            win32file.CloseHandle(pipe)
        except Exception:
            pass
