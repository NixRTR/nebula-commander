"""
Nebula Commander Windows Service.

Runs client.ncclient.run_poll_loop() (unchanged - the same poll/config/cert/DNS
logic the old elevated tray used to run in-process) as LocalSystem, so launching
Nebula and applying split-horizon DNS have full privilege without any UAC prompt.
Writes status to a shared status.json file and hosts a small named-pipe control
channel so the tray (a separate, unelevated process - see tray.py) can trigger an
immediate re-poll after enroll/settings changes instead of waiting for the next
interval tick.

Installed/managed via the MSI (installer/windows/Product.wxs's ServiceInstall/
ServiceControl elements) - this module does not register itself as part of the
supported install flow. For manual/dev use, pywin32 still provides this for free:
  python -m client.windows.service install|remove|start|stop|debug
"""
from __future__ import annotations

import json
import os
import sys
import threading


def _ensure_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    # client/windows -> client -> repo root
    root = os.path.dirname(os.path.dirname(here))
    if root not in sys.path:
        sys.path.insert(0, root)


_ensure_path()

# Must happen before importing anything that touches client.config/client.token_store
# (directly or transitively, e.g. via client.ncclient.run_poll_loop) so those modules
# pick up the shared %ProgramData% location instead of a per-user default.
from client.windows.shared_paths import enable_shared_mode, save_status, shared_root  # noqa: E402

enable_shared_mode()

import servicemanager  # noqa: E402
import win32event  # noqa: E402
import win32service  # noqa: E402
import win32serviceutil  # noqa: E402

from client.config import load_settings  # noqa: E402
from client.ncclient import run_poll_loop  # noqa: E402
from client.windows.pipe_protocol import CMD_POLL_NOW, CMD_RELOAD_SETTINGS, PIPE_NAME  # noqa: E402


def _pipe_security_attributes():
    """Grant Authenticated Users + SYSTEM/Administrators access to the control pipe,
    so the unelevated tray (running as the interactive user) can connect - a pipe
    created by a LocalSystem process otherwise defaults to SYSTEM/Admin-only."""
    import win32security

    sddl = "D:(A;;GRGW;;;AU)(A;;GA;;;SY)(A;;GA;;;BA)"
    sd = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        sddl, win32security.SDDL_REVISION_1
    )
    sa = win32security.SECURITY_ATTRIBUTES()
    sa.SECURITY_DESCRIPTOR = sd
    return sa


class NebulaCommanderService(win32serviceutil.ServiceFramework):
    _svc_name_ = "NebulaCommanderService"
    _svc_display_name_ = "Nebula Commander"
    _svc_description_ = (
        "Polls Nebula Commander for config/certs and runs the Nebula mesh VPN daemon."
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.win32_stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.stop_event = threading.Event()
        self.poll_thread: threading.Thread | None = None
        self.pipe_stop = threading.Event()
        self.pipe_thread: threading.Thread | None = None

    def SvcStop(self) -> None:
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()
        self.pipe_stop.set()
        win32event.SetEvent(self.win32_stop_event)

    def SvcDoRun(self) -> None:
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self._run()

    def _status_callback(self, status: str, message: str) -> None:
        save_status(status, message)

    def _start_poll(self) -> None:
        """(Re)start the poll loop from current settings.json. Safe to call again
        while a previous poll thread is still winding down - run_poll_loop exits
        promptly once stop_event is set."""
        settings = load_settings()
        server = (settings.get("server") or "").strip()
        interval = int(settings.get("interval") or 60)
        interval = max(10, min(3600, interval))
        nebula_path = (settings.get("nebula_path") or "").strip() or "nebula"
        accept_dns = bool(settings.get("accept_dns", False))
        output_dir = shared_root()

        if not server:
            save_status("error", "Set server URL from the tray Settings dialog")
            return

        self.stop_event.clear()
        self.poll_thread = threading.Thread(
            target=run_poll_loop,
            args=(server, output_dir, interval, nebula_path, None),
            kwargs={
                "stop_event": self.stop_event,
                "status_callback": self._status_callback,
                "accept_dns": accept_dns,
            },
            daemon=True,
        )
        self.poll_thread.start()

    def _restart_poll(self) -> None:
        """Used by the POLL_NOW/RELOAD_SETTINGS pipe commands: stop the current poll
        loop and start a fresh one, which re-reads settings.json immediately instead
        of waiting up to `interval` seconds for the change to be noticed."""
        self.stop_event.set()
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=15)
        self._start_poll()

    def _serve_pipe(self) -> None:
        import pywintypes
        import win32file
        import win32pipe

        sa = _pipe_security_attributes()
        while not self.pipe_stop.is_set():
            try:
                pipe = win32pipe.CreateNamedPipe(
                    PIPE_NAME,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE
                    | win32pipe.PIPE_READMODE_MESSAGE
                    | win32pipe.PIPE_WAIT,
                    4,  # max instances
                    4096,
                    4096,
                    0,
                    sa,
                )
            except pywintypes.error as e:
                servicemanager.LogErrorMsg(f"CreateNamedPipe failed: {e}")
                self.pipe_stop.wait(5)
                continue

            try:
                # ConnectNamedPipe blocks until a client connects or the pipe handle
                # is closed (which SvcStop doesn't do directly - pipe_stop is checked
                # on the next loop iteration after each connection completes/times out
                # naturally; the last pending ConnectNamedPipe call may block up to
                # the service's stop-pending grace period, which SCM tolerates).
                win32pipe.ConnectNamedPipe(pipe, None)
                _, data = win32file.ReadFile(pipe, 4096)
                try:
                    msg = json.loads(data.decode("utf-8"))
                except Exception:
                    msg = {}
                cmd = msg.get("cmd")
                if cmd in (CMD_POLL_NOW, CMD_RELOAD_SETTINGS):
                    self._restart_poll()
                    resp = {"ok": True}
                else:
                    resp = {"ok": False, "error": f"unknown command: {cmd!r}"}
                win32file.WriteFile(pipe, json.dumps(resp).encode("utf-8"))
            except pywintypes.error:
                pass
            finally:
                try:
                    win32pipe.DisconnectNamedPipe(pipe)
                    win32file.CloseHandle(pipe)
                except Exception as e:
                    servicemanager.LogWarningMsg(f"Pipe cleanup failed: {e}")

    def _run(self) -> None:
        save_status("starting", "Service starting")
        self.pipe_thread = threading.Thread(target=self._serve_pipe, daemon=True)
        self.pipe_thread.start()
        self._start_poll()

        win32event.WaitForSingleObject(self.win32_stop_event, win32event.INFINITE)

        self.stop_event.set()
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=15)
        save_status("stopped", "Service stopped")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No verb (install/start/debug/...) - this is how the SCM itself launches
        # the service binary, so dispatch straight into the service framework
        # instead of falling through to HandleCommandLine, which just prints a
        # usage message and exits when there are no arguments (it never attempts
        # to register with the SCM in that case).
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(NebulaCommanderService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(NebulaCommanderService)
