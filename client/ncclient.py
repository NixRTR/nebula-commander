#!/usr/bin/env python3
"""
ncclient - Nebula Commander device client (dnclient-style).

Enroll once with a code from the Nebula Commander UI, then run as a daemon
to poll for config and certs and optionally orchestrate the Nebula process
(dnclientd-style: start/restart Nebula when config changes).

  ncclient enroll --server https://nebula-commander.example.com --code XXXXXXXX
  ncclient run --server https://nebula-commander.example.com [--output-dir /etc/nebula] [--interval 60]
  ncclient install   (Linux: install systemd service, prompts for server URL and options)
  ncclient run --server ... --nebula /usr/bin/nebula
  ncclient run --server ... --restart-service nebula

Requires: requests

Copyright (C) 2025 NixRTR.  This program is free software: you can redistribute
it and/or modify it under the terms of the GNU General Public License as
published by the Free Software Foundation, version 3 or later.  See the
LICENSE file in this directory for the full text.
"""

import argparse
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Callable

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

# Env vars that can make a child load the PyInstaller-extracted libs instead of system libs.
# When we run systemctl (or any system binary), clear these so it uses system libraries only.
_SYSTEM_LIBRARY_ENV_STRIP = ("LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT", "LIBPATH")


def _env_for_system_binaries() -> dict[str, str]:
    """Return environment for running system binaries (e.g. systemctl) without PyInstaller lib path.
    Use this so systemctl loads system OpenSSL instead of the bundled libcrypto (avoids
    OPENSSL_3.4.0 not found on openSUSE and similar)."""
    env = os.environ.copy()
    for key in _SYSTEM_LIBRARY_ENV_STRIP:
        env.pop(key, None)
    return env


# systemd unit template for ncclient install (ExecStart path is substituted)
_SYSTEMD_UNIT_TEMPLATE = """[Unit]
Description=Nebula Commander device client (ncclient)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=-/etc/default/ncclient
ExecStart={ncclient_path} run
ExecStartPre=/bin/sh -c 'if [ -z "$$NEBULA_COMMANDER_SERVER" ]; then echo "Set NEBULA_COMMANDER_SERVER in /etc/default/ncclient"; exit 1; fi'
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
"""

try:
    import requests
except ImportError:
    print("ncclient requires 'requests'. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


def _server_url(server: str) -> str:
    base = server.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    return base


def _default_output_dir() -> str:
    """Default directory for config/certs; Windows-friendly."""
    if sys.platform == "win32":
        return os.path.join(os.path.expanduser("~"), ".nebula")
    return "/etc/nebula"


def cmd_enroll(server: str, code: str) -> None:
    base = _server_url(server)
    url = f"{base}/api/device/enroll"
    code = code.strip().upper()
    r = requests.post(url, json={"code": code}, timeout=30)
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        print(f"Enroll failed: {detail}", file=sys.stderr)
        sys.exit(1)
    data = r.json()
    token = data["device_token"]
    from client.token_store import set_token
    from client.config import load_settings, save_settings
    set_token(token)
    save_settings({**load_settings(), "server": base})
    print("Enrolled. Token saved to credential store.")
    print("Run: ncclient run")


def _config_path(output_dir: str) -> str:
    return os.path.join(output_dir, "config.yaml")


def _nebula_log_path(output_dir: str) -> str:
    """Path for Nebula stderr log. Default on Windows: %USERPROFILE%\\.nebula\\nebula.log"""
    return os.path.join(output_dir, "nebula.log")


def _current_process_handle():
    """Return GetCurrentProcess() as a pointer-sized handle for OpenProcessToken (fixes 64-bit)."""
    h = ctypes.windll.kernel32.GetCurrentProcess()  # type: ignore[attr-defined]
    return ctypes.c_void_p(h)


def _windows_process_is_elevated() -> bool:
    """True if the current process has elevated privileges (e.g. running as admin)."""
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        advapi32 = ctypes.windll.advapi32  # type: ignore[attr-defined]
        TOKEN_QUERY = 0x0008
        TOKEN_READ = 0x20008  # STANDARD_RIGHTS_READ | TOKEN_READ
        TokenElevation = 20  # TOKEN_ELEVATION.TokenIsElevated
        TokenElevationType = 18  # TokenElevationTypeDefault=1, Full=2, Limited=3
        TokenElevationTypeFull = 2
        handle = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
            _current_process_handle(),
            TOKEN_READ,
            ctypes.byref(handle),
        ):
            return False
        try:
            elevation = wintypes.DWORD()
            size = ctypes.sizeof(elevation)
            if advapi32.GetTokenInformation(
                handle,
                TokenElevation,
                ctypes.byref(elevation),
                size,
                ctypes.byref(wintypes.DWORD(size)),
            ):
                if elevation.value:
                    return True
            # Fallback: TokenElevation can be 0 in some contexts; check TokenElevationType.
            typ = wintypes.DWORD()
            if advapi32.GetTokenInformation(
                handle,
                TokenElevationType,
                ctypes.byref(typ),
                ctypes.sizeof(typ),
                ctypes.byref(wintypes.DWORD(ctypes.sizeof(typ))),
            ):
                return typ.value == TokenElevationTypeFull
            return False
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def get_elevation_debug_info() -> list[str]:
    """
    Return a list of human-readable debug lines about the current process token and elevation.
    Used when --console is passed to the tray to see why is_process_elevated() might be False.
    """
    lines: list[str] = []
    if sys.platform != "win32":
        return ["Elevation debug: not Windows, skipping."]
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        advapi32 = ctypes.windll.advapi32  # type: ignore[attr-defined]
        TOKEN_READ = 0x20008
        TokenElevation = 20
        TokenElevationType = 18
        TokenElevationTypeFull = 2

        proc_handle = _current_process_handle()
        lines.append("Elevation debug:")
        lines.append("  GetCurrentProcess() = %s (as void_p: %s)" % (kernel32.GetCurrentProcess(), proc_handle.value))
        handle = wintypes.HANDLE()
        ok_open = advapi32.OpenProcessToken(
            proc_handle,
            TOKEN_READ,
            ctypes.byref(handle),
        )
        err_after_open = kernel32.GetLastError()
        lines.append("  OpenProcessToken(TOKEN_READ): ok=%s, handle=%s, GetLastError=%s" % (bool(ok_open), handle.value, err_after_open))
        if not ok_open:
            lines.append("  (Common errors: 5=access denied, 6=invalid handle)")
            return lines

        try:
            elevation = wintypes.DWORD()
            size = ctypes.sizeof(elevation)
            size_arg = wintypes.DWORD(size)
            ok_elev = advapi32.GetTokenInformation(
                handle,
                TokenElevation,
                ctypes.byref(elevation),
                size,
                ctypes.byref(size_arg),
            )
            err_elev = kernel32.GetLastError()
            lines.append("  GetTokenInformation(TokenElevation=20): ok=%s, TokenIsElevated=%s, GetLastError=%s" % (bool(ok_elev), elevation.value, err_elev))
            lines.append("  (TokenElevation: 0=not elevated, 1=elevated)")

            typ = wintypes.DWORD()
            size_typ = ctypes.sizeof(typ)
            size_typ_arg = wintypes.DWORD(size_typ)
            ok_typ = advapi32.GetTokenInformation(
                handle,
                TokenElevationType,
                ctypes.byref(typ),
                size_typ,
                ctypes.byref(size_typ_arg),
            )
            err_typ = kernel32.GetLastError()
            type_names = {1: "Default", 2: "Full(elevated)", 3: "Limited"}
            lines.append("  GetTokenInformation(TokenElevationType=18): ok=%s, value=%s (%s), GetLastError=%s" % (bool(ok_typ), typ.value, type_names.get(typ.value, "?"), err_typ))
            lines.append("  (TokenElevationType: 1=Default, 2=Full, 3=Limited)")

            result = _windows_process_is_elevated()
            lines.append("  is_process_elevated() = %s" % result)
        finally:
            kernel32.CloseHandle(handle)
    except Exception as e:
        lines.append("  Exception: %s" % e)
        import traceback
        lines.append(traceback.format_exc())
    return lines


def is_process_elevated() -> bool:
    """True if the current process has elevated privileges. On non-Windows, returns True (no elevation concept)."""
    if sys.platform != "win32":
        return True
    return _windows_process_is_elevated()


def _start_nebula(nebula_bin: str, output_dir: str) -> subprocess.Popen | None:
    output_dir = os.path.expanduser(output_dir)
    config = _config_path(output_dir)
    if not os.path.exists(config):
        return None
    config_abs = os.path.abspath(config)
    if sys.platform == "win32":
        nebula_abs = os.path.abspath(nebula_bin) if os.path.dirname(nebula_bin) else (shutil.which(nebula_bin) or nebula_bin)
    else:
        nebula_abs = nebula_bin

    if sys.platform == "win32":
        # Nebula MUST run elevated (TAP device, etc.). Only start via Popen so the child
        # inherits our token; do not use ShellExecute runas (separate session, no handle).
        if not _windows_process_is_elevated():
            print(
                "Nebula requires Administrator. Run ncclient-tray as Administrator (right-click → Run as administrator).",
                file=sys.stderr,
            )
            return None
        manual_run = (
            f'To see Nebula errors, run in an elevated terminal: cd /d "{output_dir}" && "{nebula_abs}" -config "{config_abs}"'
        )
        os.makedirs(output_dir, exist_ok=True)
        nebula_to_console = os.environ.get("NCCLIENT_NEBULA_CONSOLE", "").strip().lower() in ("1", "true", "yes")
        try:
            if nebula_to_console:
                # Inherit stderr so Nebula writes directly to our console (same handle).
                # PIPE + forwarder can miss output on Windows when parent is a GUI app.
                kwargs = {
                    "stdout": subprocess.DEVNULL,
                    "stderr": None,
                    "start_new_session": True,
                    "cwd": output_dir,
                }
                proc = subprocess.Popen(
                    [nebula_abs, "-config", config_abs],
                    **kwargs,
                )
                log_note = " (stderr to console)"
            else:
                log_path = _nebula_log_path(output_dir)
                log_file = open(log_path, "a", encoding="utf-8", errors="replace")
                kwargs = {
                    "stdout": subprocess.DEVNULL,
                    "stderr": log_file,
                    "start_new_session": True,
                    "cwd": output_dir,
                    # On Windows, starting a console-mode child from a GUI parent
                    # would normally pop up a new console window. Suppress that
                    # for the tray by creating the process with no window unless
                    # NCCLIENT_NEBULA_CONSOLE is set (verbose/console mode).
                    "creationflags": subprocess.CREATE_NO_WINDOW,
                }
                proc = subprocess.Popen(
                    [nebula_abs, "-config", config_abs],
                    **kwargs,
                )
                log_note = ". Log: %s" % log_path
            print(f"Started Nebula (elevated, PID {proc.pid}){log_note}", file=sys.stderr)
            if not nebula_to_console:
                print(manual_run)
            return proc
        except FileNotFoundError:
            print(f"Nebula binary not found: {nebula_bin}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Failed to start Nebula: {e}", file=sys.stderr)
            return None

    try:
        kwargs = {
            "stdout": subprocess.DEVNULL,
            "stderr": None,  # inherit so user sees nebula errors
            "start_new_session": True,
            "cwd": output_dir,
        }
        proc = subprocess.Popen(
            [nebula_bin, "-config", config_abs],
            **kwargs,
        )
        print(f"Started Nebula (PID {proc.pid})")
        return proc
    except FileNotFoundError:
        print(f"Nebula binary not found: {nebula_bin}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"Failed to start Nebula: {e}", file=sys.stderr)
        return None


def _stop_nebula(proc: subprocess.Popen | None) -> None:
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        except Exception:
            pass
        if getattr(proc, "stderr", None) is not None and proc.stderr is not sys.stderr:
            try:
                proc.stderr.close()
            except Exception:
                pass
        print("Stopped Nebula")
        return
    if sys.platform == "win32":
        # We started Nebula elevated (runas) so we have no handle; try to stop by name.
        try:
            subprocess.run(
                ["taskkill", "/IM", "nebula.exe", "/F"],
                capture_output=True,
                timeout=10,
            )
            print("Stopped Nebula")
        except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
            pass


def _restart_systemd_service(service_name: str) -> bool:
    try:
        subprocess.run(
            ["systemctl", "restart", service_name],
            check=True,
            capture_output=True,
            timeout=30,
            env=_env_for_system_binaries(),
        )
        print(f"Restarted systemd service: {service_name}")
        return True
    except FileNotFoundError:
        print("systemctl not found (not Linux systemd?)", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as e:
        print(f"systemctl restart failed: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)
        return False


def _prompt(prompt: str, default: str = "") -> str:
    """Prompt for input; return default if user presses Enter."""
    if default:
        s = input(f"{prompt} [{default}]: ").strip()
        return s if s else default
    return input(f"{prompt}: ").strip()


def cmd_install(no_start: bool = False, non_interactive: bool = False) -> None:
    """Install systemd service (Linux only). Checks enrollment, prompts for env, writes unit and env file."""
    if sys.platform != "linux":
        print("install is only supported on Linux (systemd).", file=sys.stderr)
        sys.exit(1)
    try:
        if os.geteuid() != 0:
            print("This command must be run as root (or with sudo).", file=sys.stderr)
            sys.exit(1)
    except AttributeError:
        print("This command must be run as root (or with sudo).", file=sys.stderr)
        sys.exit(1)

    ncclient_path = shutil.which("ncclient")
    if not ncclient_path:
        print(
            "ncclient not found in PATH. Install with: pip install nebula-commander",
            file=sys.stderr,
        )
        print(
            "If ncclient is in PATH when not using sudo, run: sudo $(which ncclient) install",
            file=sys.stderr,
        )
        sys.exit(1)

    if non_interactive:
        server = (os.environ.get("NEBULA_COMMANDER_SERVER") or "").strip()
        if not server:
            print(
                "Set NEBULA_COMMANDER_SERVER or run without --non-interactive.",
                file=sys.stderr,
            )
            sys.exit(1)
        output_dir = os.environ.get("NEBULA_COMMANDER_OUTPUT_DIR", "/etc/nebula").strip() or "/etc/nebula"
        interval = os.environ.get("NEBULA_COMMANDER_INTERVAL", "60").strip() or "60"
        nebula_path = (os.environ.get("NEBULA_COMMANDER_NEBULA") or "").strip()
        restart_service = (os.environ.get("NEBULA_COMMANDER_RESTART_SERVICE") or "").strip()
    else:
        server = _prompt("Nebula Commander server URL (e.g. https://nc.example.com)", "").strip()
        if not server:
            print("Server URL is required.", file=sys.stderr)
            sys.exit(1)
        server = _server_url(server)
        output_dir = _prompt("Output directory for config/certs", "/etc/nebula").strip() or "/etc/nebula"
        interval = _prompt("Poll interval (seconds)", "60").strip() or "60"
        nebula_path = _prompt("Path to nebula binary (optional, empty to use PATH)", "").strip()
        restart_service = _prompt(
            "Systemd service to restart instead of running nebula (optional, empty for none)",
            "",
        ).strip()

    from client.token_store import get_token
    if get_token() is None:
        print("You have not enrolled yet. Run the following (as root), then run ncclient install again:", file=sys.stderr)
        print(f"  ncclient enroll --server {server} --code XXXXXXXX", file=sys.stderr)
        print("Get the code from the Nebula Commander UI: Nodes → Enroll", file=sys.stderr)
        sys.exit(1)

    env_lines = [
        f"NEBULA_COMMANDER_SERVER={server}",
        f"NEBULA_COMMANDER_OUTPUT_DIR={output_dir}",
        f"NEBULA_COMMANDER_INTERVAL={interval}",
    ]
    if nebula_path:
        env_lines.append(f"NEBULA_COMMANDER_NEBULA={nebula_path}")
    if restart_service:
        env_lines.append(f"NEBULA_COMMANDER_RESTART_SERVICE={restart_service}")

    env_content = "\n".join(env_lines) + "\n"
    unit_path = "/etc/systemd/system/ncclient.service"
    default_path = "/etc/default/ncclient"

    try:
        with open(default_path, "w") as f:
            f.write(env_content)
        print(f"Wrote {default_path}")
    except PermissionError:
        print("Could not write to /etc/default/ncclient. Run with sudo: sudo ncclient install", file=sys.stderr)
        sys.exit(1)

    unit_content = _SYSTEMD_UNIT_TEMPLATE.format(ncclient_path=ncclient_path)
    try:
        with open(unit_path, "w") as f:
            f.write(unit_content)
        print(f"Wrote {unit_path}")
    except PermissionError:
        print("Could not write to /etc/systemd/system/ncclient.service. Run with sudo: sudo ncclient install", file=sys.stderr)
        sys.exit(1)

    try:
        _sysenv = _env_for_system_binaries()
        subprocess.run(["systemctl", "daemon-reload"], check=True, capture_output=True, timeout=30, env=_sysenv)
        subprocess.run(["systemctl", "enable", "ncclient"], check=True, capture_output=True, timeout=30, env=_sysenv)
        print("Enabled ncclient service.")
    except subprocess.CalledProcessError as e:
        print(f"systemctl failed: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print("systemctl not found.", file=sys.stderr)
        sys.exit(1)

    if not no_start:
        if non_interactive:
            pass
        else:
            ans = _prompt("Start ncclient service now?", "Y").strip().upper()
            if ans in ("", "Y", "YES"):
                try:
                    subprocess.run(["systemctl", "start", "ncclient"], check=True, capture_output=True, timeout=30, env=_env_for_system_binaries())
                    print("Started ncclient service.")
                except subprocess.CalledProcessError as e:
                    print(f"systemctl start failed: {e.stderr.decode() if e.stderr else e}", file=sys.stderr)
                except FileNotFoundError:
                    print("systemctl not found.", file=sys.stderr)
            else:
                print("Run 'systemctl start ncclient' to start the service.")

    print("Done. Edit /etc/default/ncclient to change settings.")


def run_poll_loop(
    server: str,
    output_dir: str,
    interval: int,
    nebula_bin: str | None,
    restart_service: str | None,
    stop_event: threading.Event,
    status_callback: Callable[[str, str], None] | None = None,
) -> None:
    """
    Poll for config/certs and optionally run Nebula. Exits when stop_event is set.
    status_callback(status, message) is called with "idle", "connected", or "error".
    """
    from client.token_store import get_token
    base = _server_url(server)
    token = get_token()
    if not token:
        if status_callback:
            status_callback("error", "Token not found. Enroll first.")
        else:
            print("Token not found. Run 'ncclient enroll' first.", file=sys.stderr)
            sys.exit(1)
        return
    url = f"{base}/api/device/config"
    output_dir = os.path.expanduser(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    last_etag: str | None = None
    nebula_proc: subprocess.Popen | None = None

    def _sleep() -> None:
        elapsed = 0
        while elapsed < interval and not stop_event.is_set():
            stop_event.wait(timeout=1)
            elapsed += 1

    if not status_callback:
        if nebula_bin:
            print(f"Orchestrating Nebula: {nebula_bin} (restart on config change)")
        if restart_service:
            print(f"Orchestrating service: systemctl restart {restart_service} on config change")
        print(f"Polling {url} every {interval}s. Output: {output_dir}. Ctrl+C to stop.")
    elif status_callback:
        status_callback("idle", "Polling...")

    try:
        while not stop_event.is_set():
            try:
                headers = {"Authorization": f"Bearer {token}"}
                if last_etag is not None:
                    headers["If-None-Match"] = last_etag
                r = requests.get(url, headers=headers, timeout=30)
                if r.status_code == 401:
                    if status_callback:
                        status_callback("error", "Token invalid or expired. Re-enroll.")
                        return
                    print("Token invalid or expired. Re-enroll with a new code.", file=sys.stderr)
                    sys.exit(1)
                if r.status_code == 304:
                    if nebula_bin and (nebula_proc is None or nebula_proc.poll() is not None):
                        nebula_proc = _start_nebula(nebula_bin, output_dir)
                    _sleep()
                    continue
                if not r.ok:
                    msg = f"Poll failed: {r.status_code} {r.text[:200]}"
                    if status_callback:
                        status_callback("error", msg)
                    else:
                        print(msg, file=sys.stderr)
                    _sleep()
                    continue
                etag_raw = r.headers.get("ETag")
                config_id = etag_raw.strip('"') if etag_raw is not None else hashlib.sha256(r.content).hexdigest()
                if last_etag is not None and config_id == last_etag:
                    if nebula_bin and (nebula_proc is None or nebula_proc.poll() is not None):
                        nebula_proc = _start_nebula(nebula_bin, output_dir)
                    _sleep()
                    continue
                last_etag = config_id
                config_path = _config_path(output_dir)
                with open(config_path, "wb") as f:
                    f.write(r.content)
                if not status_callback:
                    print(f"Wrote {config_path}")
                if status_callback:
                    status_callback("connected", "Config updated")
                if nebula_bin:
                    _stop_nebula(nebula_proc)
                    nebula_proc = _start_nebula(nebula_bin, output_dir)
                if restart_service:
                    _restart_systemd_service(restart_service)
            except requests.RequestException as e:
                err = str(e)
                if status_callback:
                    status_callback("error", err)
                else:
                    print(f"Request error: {e}", file=sys.stderr)
            _sleep()
    finally:
        _stop_nebula(nebula_proc)


def cmd_run(
    server: str,
    output_dir: str,
    interval: int,
    nebula_bin: str | None,
    restart_service: str | None,
) -> None:
    stop_event = threading.Event()

    def noop_callback(_status: str, _message: str) -> None:
        pass

    try:
        signal.signal(signal.SIGTERM, lambda s, f: stop_event.set())
    except (ValueError, OSError):
        pass
    try:
        run_poll_loop(
            server,
            output_dir,
            interval,
            nebula_bin,
            restart_service,
            stop_event=stop_event,
            status_callback=noop_callback,
        )
    except KeyboardInterrupt:
        print("\nStopped.")
        stop_event.set()
    # run_poll_loop already stopped nebula and returned


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Nebula Commander device client (dnclient/dnclientd-style). Enroll once, then run to poll config and certs and optionally start/restart Nebula."
    )
    ap.add_argument("--server", "-s", default=os.environ.get("NEBULA_COMMANDER_SERVER"), help="Nebula Commander base URL (default: NEBULA_COMMANDER_SERVER env)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_install = sub.add_parser("install", help="Install systemd service (Linux only)")
    p_install.add_argument("--no-start", action="store_true", help="Do not start the service after enable")
    p_install.add_argument("--non-interactive", action="store_true", help="Use env vars only, no prompts")

    p_enroll = sub.add_parser("enroll", help="Enroll with a one-time code from the UI")
    p_enroll.add_argument("--code", "-c", required=True, help="Enrollment code")

    p_run = sub.add_parser("run", help="Run daemon: poll for config and certs, optionally start/restart Nebula (dnclientd-style)")
    p_run.add_argument("--output-dir", "-o", default=None, help="Directory to write config.yaml, ca.crt, host.crt (default: /etc/nebula on Linux, ~/.nebula on Windows)")
    p_run.add_argument("--interval", "-i", type=int, default=60, help="Poll interval in seconds (default: 60)")
    p_run.add_argument("--nebula", "-n", metavar="PATH", help="Path to nebula binary if not in PATH (default: run 'nebula' from PATH)")
    p_run.add_argument("--restart-service", "-r", metavar="NAME", help="Restart this systemd service after config change instead of running nebula (e.g. nebula)")

    args = ap.parse_args()
    from client.config import load_settings
    server = (args.server or "").strip() or (load_settings().get("server") or "").strip() or None
    if args.cmd == "run" and not server:
        print("Set --server or NEBULA_COMMANDER_SERVER to your Nebula Commander URL.", file=sys.stderr)
        sys.exit(1)
    if args.cmd == "enroll" and not server:
        print("Set --server to your Nebula Commander URL.", file=sys.stderr)
        sys.exit(1)

    if args.cmd == "install":
        cmd_install(
            no_start=getattr(args, "no_start", False),
            non_interactive=getattr(args, "non_interactive", False),
        )
    elif args.cmd == "enroll":
        cmd_enroll(server, args.code)
    elif args.cmd == "run":
        if getattr(args, "nebula", None) and getattr(args, "restart_service", None):
            print("Use only one of --nebula or --restart-service.", file=sys.stderr)
            sys.exit(1)
        nebula_bin = getattr(args, "nebula", None)
        restart_service = getattr(args, "restart_service", None)
        # Default: run nebula from PATH; use --nebula only when it's in a non-standard place.
        if nebula_bin is None and restart_service is None:
            nebula_bin = "nebula"
        cmd_run(
            server,
            args.output_dir or _default_output_dir(),
            args.interval,
            nebula_bin,
            restart_service,
        )
if __name__ == "__main__":
    main()
