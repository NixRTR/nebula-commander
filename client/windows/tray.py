"""
Nebula Commander Windows system-tray app: configuration/control UI for the
Nebula Commander Windows Service (see client/windows/service.py), which does the
actual polling/config/cert/DNS/Nebula-process work as LocalSystem.

This process itself runs UNELEVATED - no UAC prompt to launch it. It enrolls,
edits settings, manages the Nebula binary, and starts/stops/restarts the service,
all by writing to a shared %ProgramData%\\nebula-commander\\ location (see
client/windows/shared_paths.py) and sending small control commands to the service
over a named pipe (client/windows/pipe_protocol.py); it reads the service's
self-reported status from a shared status.json file rather than running any
poll loop itself.

Run from repo root: python -m client.windows.tray
Terminal output: use --console, -v, or --verbose to print log messages to stderr.
Alternatively: set NCCLIENT_TRAY_VERBOSE=1, or run from a console (stdout is a TTY).
"""
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox

_console_flags = {"--console", "--verbose", "-v"}
_verbose_flag = any(f in sys.argv for f in _console_flags)
if _verbose_flag:
    for f in _console_flags:
        while f in sys.argv:
            sys.argv.remove(f)
# When running as a frozen Windows exe (PyInstaller) with --console, attach a console so output is visible
if _verbose_flag and sys.platform == "win32" and getattr(sys, "frozen", False):
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.AllocConsole()
        sys.stderr = open("CON", "w", encoding="utf-8")
        sys.stdout = open("CON", "w", encoding="utf-8")
    except Exception:
        pass
_verbose_env = os.environ.get("NCCLIENT_TRAY_VERBOSE", "").strip() in ("1", "true", "yes")
VERBOSE = _verbose_flag or _verbose_env or (hasattr(sys.stdout, "isatty") and sys.stdout.isatty())


def _log(msg: str) -> None:
    if VERBOSE:
        print(f"[tray] {msg}", file=sys.stderr, flush=True)

# Ensure repo root (parent of client/) is on path when run as __main__
def _ensure_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    # client/windows -> client -> repo root
    root = os.path.dirname(os.path.dirname(here))
    if root not in sys.path:
        sys.path.insert(0, root)

_ensure_path()

# Must happen before any client.config/client.token_store access (directly or via
# cmd_enroll) so this process reads/writes the same shared %ProgramData% location
# the service uses, instead of the per-user default.
from client.windows.shared_paths import enable_shared_mode, shared_root, load_status  # noqa: E402

enable_shared_mode()

from client.config import config_dir, load_settings, save_settings  # noqa: E402
from client.ncclient import cmd_enroll  # noqa: E402
from client.nebula_download import (  # noqa: E402
    NEBULA_RELEASES_URL,
    download_nebula_to_dir as _download_nebula_to_dir_base,
    get_nebula_version as _get_nebula_version_base,
    fetch_latest_nebula_tag as _fetch_latest_nebula_tag_base,
    is_newer_version,
)
from client.token_store import get_token  # noqa: E402
from client.windows import autostart  # noqa: E402
from client.windows import dialogs  # noqa: E402
from client.windows import icons  # noqa: E402
from client.windows import pipe_protocol  # noqa: E402

try:
    import pystray
    from pystray import MenuItem as Item
except ImportError:
    print("Tray app requires pystray and Pillow. Install with: pip install pystray Pillow", file=sys.stderr)
    sys.exit(1)

SERVICE_NAME = "NebulaCommanderService"


def _nebula_download_dir() -> str:
    """Directory where we install downloaded nebula.exe: config_dir/nebula/
    (config_dir() is redirected to the shared %ProgramData% root above, so this
    is the same location the service looks for the binary in.)"""
    return os.path.join(config_dir(), "nebula")


def _downloaded_nebula_path() -> str:
    """Path to nebula.exe in the shared nebula dir, if it exists, else empty."""
    exe = os.path.join(_nebula_download_dir(), "nebula.exe")
    return exe if os.path.isfile(exe) else ""


def _default_nebula_path() -> str:
    """Default: previously downloaded exe in the shared dir, or 'nebula' on PATH."""
    return _downloaded_nebula_path() or "nebula"


def _effective_nebula_path_from_settings(settings: dict) -> str:
    """Nebula path from settings, or default; ignores stale _MEI paths (e.g. after --no-nebula rebuild)."""
    raw = (settings.get("nebula_path") or "").strip()
    if dialogs._is_stale_nebula_path(raw):
        raw = ""
    return raw or _default_nebula_path()


def _resolve_nebula_bin(path: str | None) -> str | None:
    """Return path to nebula binary if it exists or is on PATH, else None."""
    path = (path or "").strip()
    if not path:
        return None
    if os.path.isfile(path):
        return path
    return shutil.which(path)


# Nebula download/version-check logic lives in client/nebula_download.py, shared with
# windows/build.py's build-time bundling. These are thin wrappers that plug in tray's
# own verbosity-gated logger.

def _download_nebula_to_dir(version: str, dest_dir: str) -> tuple[bool, str | None, str]:
    return _download_nebula_to_dir_base(version, dest_dir, log=_log)


def _get_nebula_version(nebula_bin: str) -> str | None:
    return _get_nebula_version_base(nebula_bin, log=_log)


def _fetch_latest_nebula_tag() -> str | None:
    return _fetch_latest_nebula_tag_base(log=_log)


def _add_dir_to_user_path(dir_path: str) -> bool:
    """Add directory to the current user's PATH (Windows). Returns True on success."""
    if sys.platform != "win32":
        return False
    import winreg
    dir_abs = os.path.abspath(dir_path)
    if not os.path.isdir(dir_abs):
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            "Environment",
            0,
            winreg.KEY_READ | winreg.KEY_WRITE,
        )
        try:
            path_val, _ = winreg.QueryValueEx(key, "Path")
        except OSError:
            path_val = ""
        key.Close()
        parts = [p.strip() for p in (path_val or "").split(";") if p.strip()]
        if dir_abs in parts:
            return True
        parts.append(dir_abs)
        new_path = ";".join(parts)
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            "Environment",
            0,
            winreg.KEY_WRITE,
        )
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
        key.Close()
        _log(f"Added {dir_abs} to user PATH")
        return True
    except Exception as e:
        _log(f"Add to user PATH failed: {e}")
        return False


def _service_state() -> str:
    """One of 'running', 'stopped', 'transitioning', or 'not_installed'."""
    try:
        import win32service
        import win32serviceutil
        status = win32serviceutil.QueryServiceStatus(SERVICE_NAME)
        state = status[1]
        if state == win32service.SERVICE_RUNNING:
            return "running"
        if state == win32service.SERVICE_STOPPED:
            return "stopped"
        return "transitioning"
    except Exception:
        return "not_installed"


def _notify_service(cmd: str) -> None:
    """Best-effort: ask the service to act immediately instead of waiting for its
    next poll cycle. Failures (service not running/installed) are logged and
    otherwise ignored - the change is already saved and will be picked up whenever
    the service next starts or polls."""
    result = pipe_protocol.send_command(cmd)
    if not result.get("ok"):
        _log(f"_notify_service({cmd!r}): {result.get('error')}")


def main() -> None:
    if sys.platform != "win32":
        print("Windows tray app is Windows-only.", file=sys.stderr)
        sys.exit(1)

    _log(f"main thread id={threading.current_thread().ident}")
    _log(f"shared root: {shared_root()}")

    settings = load_settings()
    server = (settings.get("server") or "").strip() or "https://"
    interval = int(settings.get("interval") or 60)
    interval = max(10, min(3600, interval))
    nebula_path = _effective_nebula_path_from_settings(settings)

    current_status = "idle"
    current_message = "Nebula Commander"
    icon_obj: pystray.Icon | None = None
    tk_root: tk.Tk | None = None
    # Queue for tray -> main thread: only main thread touches Tk (required on Windows)
    ui_queue: queue.Queue[str] = queue.Queue()

    def update_ui(status: str, message: str) -> None:
        nonlocal current_status, current_message
        current_status = status
        current_message = message or "Nebula Commander"
        if icon_obj:
            try:
                img = icons.icon_image(status)
                icon_obj.icon = img
                icon_obj.title = current_message[:128]
            except Exception:
                pass

    def refresh_status() -> None:
        """Poll the service's self-reported status + its SCM state on a timer,
        replacing the old in-process status_callback push (there's no poll loop in
        this process to push from anymore)."""
        svc_state = _service_state()
        if svc_state == "not_installed":
            update_ui("error", "Service not installed - reinstall Nebula Commander")
        elif svc_state == "stopped":
            update_ui("idle", "Service stopped")
        else:
            status = load_status()
            update_ui(status.get("state") or "idle", status.get("message") or "Nebula Commander")
        if tk_root:
            tk_root.after(2000, refresh_status)

    def on_enroll(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _log("on_enroll called (tray thread), putting 'enroll' in queue")
        ui_queue.put("enroll")

    def _do_enroll(parent: tk.Tk | None) -> None:
        _log("_do_enroll: opening Enroll dialog (parent=%s)" % (parent is not None))
        result = dialogs.enroll_dialog(parent)
        _log("_do_enroll: dialog closed, result=%s" % (result is not None))
        if result:
            server_url, code = result
            try:
                cmd_enroll(server_url, code)
                messagebox.showinfo("Enroll", "Enrolled successfully.", parent=parent)
                _notify_service(pipe_protocol.CMD_POLL_NOW)
            except SystemExit as e:
                msg = "Enroll failed. Check server URL and code."
                if e.code and str(e.code).strip():
                    msg = str(e.code)
                messagebox.showerror("Enroll", msg, parent=parent)
            except Exception as e:
                messagebox.showerror("Enroll", str(e), parent=parent)

    def on_settings(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _log("on_settings called (tray thread), putting 'settings' in queue")
        ui_queue.put("settings")

    def _do_settings(parent: tk.Tk | None) -> None:
        nonlocal server, interval, nebula_path
        _log("_do_settings: opening Settings dialog (parent=%s)" % (parent is not None))
        s = load_settings()
        raw_nebula = (s.get("nebula_path") or "").strip()
        if dialogs._is_stale_nebula_path(raw_nebula):
            raw_nebula = ""
        accept_dns = bool(s.get("accept_dns", False))
        result = dialogs.settings_dialog(parent, server, interval, raw_nebula, accept_dns)
        _log("_do_settings: dialog closed, result=%s" % (result is not None))
        if result:
            server, interval, nebula_path, accept_dns = result
            save_settings({
                "server": server,
                "interval": interval,
                "nebula_path": nebula_path,
                "accept_dns": accept_dns,
                "node_id": s.get("node_id"),
            })
            _notify_service(pipe_protocol.CMD_RELOAD_SETTINGS)

    def on_manage_nebula(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _log("on_manage_nebula: putting 'manage_nebula' in queue")
        ui_queue.put("manage_nebula")

    def _do_manage_nebula(parent: tk.Tk | None) -> None:
        """Check/install/upgrade the Nebula binary. The service (not this process)
        actually runs it - after a change here we just tell the service to reload."""
        nonlocal nebula_path
        s = load_settings()
        nebula_path = _effective_nebula_path_from_settings(s)
        nebula_bin = _resolve_nebula_bin(nebula_path)

        if nebula_bin is None:
            install = messagebox.askyesno(
                "Nebula not found",
                "Nebula was not found. Install the latest release?",
                parent=parent,
            )
            if not install:
                messagebox.showinfo(
                    "Nebula required",
                    "You need Nebula installed to run the VPN.\n\n"
                    "Download it from the releases page (will open in your browser).",
                    parent=parent,
                )
                webbrowser.open(NEBULA_RELEASES_URL)
                return
            default_dir = _nebula_download_dir()
            dir_path = filedialog.askdirectory(
                title="Choose install directory for Nebula",
                initialdir=default_dir if os.path.isdir(default_dir) else _nebula_download_dir(),
                parent=parent,
            )
            if not dir_path:
                return
            latest_tag = _fetch_latest_nebula_tag()
            if not latest_tag:
                messagebox.showerror("Install Nebula", "Could not fetch latest version. Check your connection.", parent=parent)
                return
            ok, exe_path, err = _download_nebula_to_dir(latest_tag, dir_path)
            if not ok:
                messagebox.showerror("Install Nebula", err or "Download failed.", parent=parent)
                return
            if dir_path != _nebula_download_dir():
                _add_dir_to_user_path(dir_path)
            nebula_path = exe_path
            save_settings({**load_settings(), "nebula_path": nebula_path})
            messagebox.showinfo(
                "Nebula installed",
                f"Nebula installed to:\n{exe_path}",
                parent=parent,
            )
            _notify_service(pipe_protocol.CMD_RELOAD_SETTINGS)
            if icon_obj and hasattr(icon_obj, "update_menu"):
                icon_obj.update_menu()
            return

        local_ver = _get_nebula_version(nebula_bin)
        latest_tag = _fetch_latest_nebula_tag()
        if latest_tag and local_ver and is_newer_version(local_ver, latest_tag):
            upgrade = messagebox.askyesno(
                "Upgrade Nebula",
                f"A newer Nebula version ({latest_tag}) is available. Upgrade?",
                parent=parent,
            )
            if upgrade:
                dest_dir = os.path.dirname(nebula_bin)
                try:
                    writable = os.access(dest_dir, os.W_OK) and os.path.isfile(nebula_bin)
                except Exception:
                    writable = False
                if not writable:
                    dest_dir = filedialog.askdirectory(
                        title="Choose directory for Nebula upgrade",
                        initialdir=_nebula_download_dir(),
                        parent=parent,
                    )
                    if not dest_dir:
                        return
                ok, exe_path, err = _download_nebula_to_dir(latest_tag, dest_dir)
                if ok:
                    if dest_dir != os.path.dirname(nebula_bin):
                        _add_dir_to_user_path(dest_dir)
                    nebula_path = exe_path
                    save_settings({**load_settings(), "nebula_path": nebula_path})
                    messagebox.showinfo("Nebula upgraded", f"Nebula updated to {latest_tag} at:\n{exe_path}", parent=parent)
                    _notify_service(pipe_protocol.CMD_RELOAD_SETTINGS)
                    if icon_obj and hasattr(icon_obj, "update_menu"):
                        icon_obj.update_menu()
                else:
                    messagebox.showerror("Upgrade Nebula", err or "Download failed.", parent=parent)
                return

        messagebox.showinfo("Nebula", f"Nebula is up to date ({local_ver or 'unknown version'}).", parent=parent)

    def on_start_service(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        ui_queue.put("start_service")

    def _do_start_service(parent: tk.Tk | None) -> None:
        try:
            import win32serviceutil
            win32serviceutil.StartService(SERVICE_NAME)
        except Exception as e:
            messagebox.showerror("Service", f"Could not start the service:\n{e}", parent=parent)
        if icon_obj and hasattr(icon_obj, "update_menu"):
            icon_obj.update_menu()

    def on_stop_service(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        ui_queue.put("stop_service")

    def _do_stop_service(parent: tk.Tk | None) -> None:
        try:
            import win32serviceutil
            win32serviceutil.StopService(SERVICE_NAME)
        except Exception as e:
            messagebox.showerror("Service", f"Could not stop the service:\n{e}", parent=parent)
        if icon_obj and hasattr(icon_obj, "update_menu"):
            icon_obj.update_menu()

    def on_restart_service(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        ui_queue.put("restart_service")

    def _do_restart_service(parent: tk.Tk | None) -> None:
        try:
            import win32serviceutil
            win32serviceutil.RestartService(SERVICE_NAME)
        except Exception as e:
            messagebox.showerror("Service", f"Could not restart the service:\n{e}", parent=parent)
        if icon_obj and hasattr(icon_obj, "update_menu"):
            icon_obj.update_menu()

    def on_open_folder(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        folder = shared_root()
        os.makedirs(folder, exist_ok=True)
        os.startfile(folder)

    def on_autostart(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if autostart.is_autostart_enabled():
            autostart.disable_autostart()
        else:
            if getattr(sys, "frozen", False):
                autostart.enable_autostart(sys.executable)
            else:
                # Create a launcher batch so -m client.windows.tray runs with correct cwd
                appdata = os.environ.get("APPDATA", os.path.expanduser("~"))
                dir_path = os.path.join(appdata, "nebula-commander")
                os.makedirs(dir_path, exist_ok=True)
                bat_path = os.path.join(dir_path, "ncclient-tray-launch.bat")
                repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if not os.path.isfile(pythonw):
                    pythonw = sys.executable
                content = f'@echo off\ncd /d "{repo_root}"\n"{pythonw}" -m client.windows.tray\n'
                with open(bat_path, "w", encoding="utf-8") as f:
                    f.write(content)
                autostart.enable_autostart(bat_path)
        if icon_obj and hasattr(icon_obj, "update_menu"):
            icon_obj.update_menu()

    def on_exit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _log("on_exit called (tray thread): put 'quit', icon.stop()")
        ui_queue.put("quit")
        icon.stop()
        _log("on_exit: icon.stop() returned")

    def on_configure(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _log("on_configure: putting 'settings' in queue")
        ui_queue.put("settings")

    def on_nebula_commander(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if server and server != "https://":
            webbrowser.open(server)

    def make_menu() -> pystray.Menu:
        nonlocal server, interval, nebula_path
        s = load_settings()
        server = (s.get("server") or "").strip() or "https://"
        interval = max(10, min(3600, int(s.get("interval") or 60)))
        nebula_path = _effective_nebula_path_from_settings(s)

        svc_state = _service_state()
        items = [
            Item("Settings", on_configure, default=True),
            Item("Enroll", on_enroll),
            Item("Manage Nebula", on_manage_nebula),
        ]
        if svc_state == "running":
            items.append(Item("Stop Service", on_stop_service))
            items.append(Item("Restart Service", on_restart_service))
        elif svc_state == "stopped":
            items.append(Item("Start Service", on_start_service))
        elif svc_state == "transitioning":
            items.append(Item("Service starting/stopping...", lambda icon, item: None, enabled=False))
        else:
            items.append(Item("Service not installed", lambda icon, item: None, enabled=False))
        if get_token() is not None and server and server != "https://":
            items.append(Item("Nebula Commander", on_nebula_commander))
        items.append(Item("Open Data Folder", on_open_folder))
        items.append(Item("Run On Startup", on_autostart, checked=lambda item: autostart.is_autostart_enabled()))
        items.append(Item("Exit", on_exit))
        return pystray.Menu(*items)

    # Hidden tk root for dialogs. Tray runs in background thread; main thread drains ui_queue
    # so all Tk work (dialogs, quit) runs on main thread (required on Windows).
    tk_root = tk.Tk()
    tk_root.withdraw()

    icon_obj = pystray.Icon(
        "nebula_commander",
        icons.icon_idle(),
        current_message,
        menu=pystray.Menu(lambda: make_menu()),
    )

    def process_ui_queue() -> None:
        # Process at most one message per run, then reschedule.
        try:
            msg = ui_queue.get_nowait()
        except queue.Empty:
            if tk_root:
                tk_root.after(100, process_ui_queue)
            return
        _log(f"process_ui_queue: got message '{msg}' (main thread id={threading.current_thread().ident})")
        if msg == "quit":
            _log("process_ui_queue: calling tk_root.quit()")
            tk_root.quit()
            return
        if msg == "settings":
            _do_settings(tk_root)
        if msg == "enroll":
            _do_enroll(tk_root)
        if msg == "manage_nebula":
            _do_manage_nebula(tk_root)
        if msg == "start_service":
            _do_start_service(tk_root)
        if msg == "stop_service":
            _do_stop_service(tk_root)
        if msg == "restart_service":
            _do_restart_service(tk_root)
        if tk_root:
            tk_root.after(100, process_ui_queue)

    def run_icon() -> None:
        _log(f"icon thread started (id={threading.current_thread().ident})")
        icon_obj.run()
        _log("icon thread: icon.run() returned")

    icon_thread = threading.Thread(target=run_icon, daemon=True)
    icon_thread.start()
    _log("scheduled first process_ui_queue in 100ms, entering mainloop")
    tk_root.after(100, process_ui_queue)
    tk_root.after(500, refresh_status)
    try:
        tk_root.mainloop()
    except KeyboardInterrupt:
        _log("Ctrl+C received, exiting gracefully")
        try:
            icon_obj.stop()
        except Exception:
            pass
        try:
            tk_root.destroy()
        except Exception:
            pass
        sys.exit(0)
    _log("mainloop() returned")
    try:
        tk_root.destroy()
    except Exception as e:
        _log(f"destroy: {e}")
    _log("exiting main(); process should terminate")
    sys.exit(0)


if __name__ == "__main__":
    main()
