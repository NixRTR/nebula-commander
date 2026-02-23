"""
Nebula Commander Windows system-tray app. Enroll, poll for config/certs, optionally run Nebula.
Run from repo root: python -m client.windows.tray

Run with: python -m client.windows.tray  (from repo root)
Verbose logging: set NCCLIENT_TRAY_VERBOSE=1, or run from a console (stdout is a TTY).
"""
import json
import os
import queue
import shutil
import sys
import threading
import tkinter as tk
import webbrowser
import zipfile
from tkinter import messagebox

_verbose_env = os.environ.get("NCCLIENT_TRAY_VERBOSE", "").strip() in ("1", "true", "yes")
VERBOSE = _verbose_env or (hasattr(sys.stdout, "isatty") and sys.stdout.isatty())


def _log(msg: str) -> None:
    if VERBOSE:
        print(f"[tray] {msg}", flush=True)

# Ensure repo root (parent of client/) is on path when run as __main__
def _ensure_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    # client/windows -> client -> repo root
    root = os.path.dirname(os.path.dirname(here))
    if root not in sys.path:
        sys.path.insert(0, root)

_ensure_path()

from client.config import load_settings, save_settings
from client.ncclient import (
    run_poll_loop,
    cmd_enroll,
    _token_path,
    _default_output_dir,
)
from client.webui.server import run_server_thread
from client.windows import autostart
from client.windows import dialogs
from client.windows import icons

try:
    import pystray
    from pystray import MenuItem as Item
    from PIL import Image
except ImportError as e:
    print("Tray app requires pystray and Pillow. Install with: pip install pystray Pillow", file=sys.stderr)
    sys.exit(1)


def _nebula_download_dir() -> str:
    """Directory where we install downloaded nebula.exe: ~/.config/nebula-commander/nebula/"""
    return os.path.join(os.path.dirname(_token_path()), "nebula")


def _downloaded_nebula_path() -> str:
    """Path to nebula.exe in ~/.config/nebula-commander/nebula/ if it exists, else empty."""
    exe = os.path.join(_nebula_download_dir(), "nebula.exe")
    return exe if os.path.isfile(exe) else ""


def _default_nebula_path() -> str:
    return dialogs.get_bundled_nebula_path() or _downloaded_nebula_path() or "nebula"


def _resolve_nebula_bin(path: str | None) -> str | None:
    """Return path to nebula binary if it exists or is on PATH, else None."""
    path = (path or "").strip()
    if not path:
        return None
    if os.path.isfile(path):
        return path
    # e.g. "nebula" or "nebula.exe" on PATH
    return shutil.which(path)


NEBULA_VERSION_DEFAULT = "v1.10.2"
NEBULA_URL_TEMPLATE = "https://github.com/slackhq/nebula/releases/download/{version}/nebula-windows-amd64.zip"


def _download_nebula_to_config(version: str) -> tuple[bool, str | None, str]:
    """
    Download Nebula Windows binary and extract to ~/.config/nebula-commander/nebula/nebula.exe.
    Returns (success, path_to_exe or None, error_message).
    """
    import tempfile
    import traceback
    import urllib.request
    url = NEBULA_URL_TEMPLATE.format(version=version)
    dest_dir = _nebula_download_dir()
    exe_path = os.path.join(dest_dir, "nebula.exe")
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(tempfile.gettempdir(), "nebula-windows-amd64.zip")
    _log(f"Download Nebula: version={version}, url={url}")
    _log(f"Download Nebula: dest_dir={dest_dir}, zip_path={zip_path}")
    try:
        _log("Download Nebula: requesting URL...")
        urllib.request.urlretrieve(url, zip_path)
        _log(f"Download Nebula: saved to {zip_path}, size={os.path.getsize(zip_path)}")
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        _log(f"Download Nebula failed: {err_msg}")
        if VERBOSE:
            traceback.print_exc()
        return False, None, err_msg
    try:
        _log("Download Nebula: opening zip...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            _log(f"Download Nebula: archive entries: {names}")
            for name in names:
                if name.endswith("nebula.exe"):
                    with zf.open(name) as src:
                        with open(exe_path, "wb") as dst:
                            dst.write(src.read())
                    _log(f"Download Nebula: extracted to {exe_path}")
                    return True, exe_path, ""
            _log("Download Nebula: nebula.exe not found in archive")
            return False, None, "nebula.exe not found in archive"
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        _log(f"Download Nebula extract failed: {err_msg}")
        if VERBOSE:
            traceback.print_exc()
        return False, None, err_msg
    finally:
        try:
            os.remove(zip_path)
            _log("Download Nebula: removed temp zip")
        except OSError as e:
            _log(f"Download Nebula: could not remove temp zip: {e}")


def main() -> None:
    if sys.platform != "win32":
        print("Windows tray app is Windows-only.", file=sys.stderr)
        sys.exit(1)

    _log(f"main thread id={threading.current_thread().ident}")

    settings = load_settings()
    server = (settings.get("server") or "").strip() or "https://"
    output_dir = (settings.get("output_dir") or "").strip() or _default_output_dir()
    interval = int(settings.get("interval") or 60)
    if interval < 10:
        interval = 10
    elif interval > 3600:
        interval = 3600
    nebula_path = (settings.get("nebula_path") or "").strip() or _default_nebula_path()

    token_path = _token_path()
    stop_event = threading.Event()
    poll_thread: threading.Thread | None = None
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
                # pystray expects PIL Image
                icon_obj.icon = img
                icon_obj.title = current_message[:128]
            except Exception:
                pass

    def run_poll() -> None:
        nonlocal poll_thread, server, output_dir, interval, nebula_path
        # Re-read settings so Web UI or tray menu has latest (e.g. when starting from API)
        s = load_settings()
        server = (s.get("server") or "").strip() or "https://"
        output_dir = (s.get("output_dir") or "").strip() or _default_output_dir()
        interval = int(s.get("interval") or 60)
        interval = max(10, min(3600, interval))
        nebula_path = (s.get("nebula_path") or "").strip() or _default_nebula_path()

        if not server or server == "https://":
            update_ui("error", "Set server URL in Settings")
            return
        if not os.path.isfile(token_path):
            update_ui("error", "Enroll first")
            return
        # Only pass a nebula path if the binary exists or is on PATH; else poll without starting Nebula
        nebula_bin = _resolve_nebula_bin(nebula_path)
        stop_event.clear()
        def callback(s: str, m: str) -> None:
            update_ui(s, m)
        poll_thread = threading.Thread(
            target=run_poll_loop,
            args=(server, None, output_dir, interval, nebula_bin, None),
            kwargs={"stop_event": stop_event, "status_callback": callback},
            daemon=True,
        )
        poll_thread.start()

    def stop_poll() -> None:
        stop_event.set()
        if poll_thread and poll_thread.is_alive():
            poll_thread.join(timeout=interval + 5)

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
                cmd_enroll(server_url, code, None)
                messagebox.showinfo("Enroll", "Enrolled successfully.", parent=parent)
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
        nonlocal server, output_dir, interval, nebula_path
        _log("_do_settings: opening Settings dialog (parent=%s)" % (parent is not None))
        result = dialogs.settings_dialog(parent, server, output_dir, interval, nebula_path)
        _log("_do_settings: dialog closed, result=%s" % (result is not None))
        if result:
            server, output_dir, interval, nebula_path = result
            save_settings({
                "server": server,
                "output_dir": output_dir,
                "interval": interval,
                "nebula_path": nebula_path,
            })
            update_ui(current_status, current_message)

    def on_start_stop(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if poll_thread and poll_thread.is_alive():
            stop_poll()
            update_ui("idle", "Stopped")
        else:
            run_poll()
        if icon_obj and hasattr(icon_obj, "update_menu"):
            icon_obj.update_menu()

    def on_open_folder(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        os.makedirs(output_dir, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(output_dir)
        else:
            import subprocess
            subprocess.run(["xdg-open", output_dir], check=False)

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

    def on_download_nebula(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _log("on_download_nebula: putting 'download_nebula' in queue")
        ui_queue.put("download_nebula")

    def _do_download_nebula(parent: tk.Tk | None) -> None:
        nonlocal nebula_path
        _log("_do_download_nebula: starting download (may take a moment)")
        ok, exe_path, error_msg = _download_nebula_to_config(NEBULA_VERSION_DEFAULT)
        if ok and exe_path:
            # Use downloaded path; if user had no custom path, this becomes the default
            nebula_path = exe_path
            save_settings({
                "server": server,
                "output_dir": output_dir,
                "interval": interval,
                "nebula_path": nebula_path,
            })
            update_ui(current_status, current_message)
            if icon_obj and hasattr(icon_obj, "update_menu"):
                icon_obj.update_menu()
            if parent:
                messagebox.showinfo("Download Nebula", f"Nebula installed to:\n{exe_path}", parent=parent)
        else:
            if parent:
                detail = f"Check your connection and try again.\n\n{error_msg}" if error_msg else "Check your connection and try again."
                messagebox.showerror("Download Nebula", detail, parent=parent)

    def on_exit(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _log("on_exit called (tray thread): stop_poll, put 'quit', icon.stop()")
        stop_poll()
        ui_queue.put("quit")
        icon.stop()
        _log("on_exit: icon.stop() returned")

    # Start config Web UI server (used by "Configure" and by ncclient web)
    web_thread, config_url = run_server_thread(
        get_status=lambda: (current_status, current_message),
        set_polling=lambda start: (run_poll() if start else stop_poll()),
    )

    def on_configure(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        webbrowser.open(config_url)

    def on_nebula_commander(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if server and server != "https://":
            webbrowser.open(server)

    def _nebula_found() -> bool:
        effective = (nebula_path or "").strip() or _default_nebula_path()
        return _resolve_nebula_bin(effective) is not None

    def make_menu() -> pystray.Menu:
        nonlocal server, output_dir, interval, nebula_path
        # Re-read settings so Web UI changes are reflected (e.g. server URL for Nebula Commander link)
        s = load_settings()
        server = (s.get("server") or "").strip() or "https://"
        output_dir = (s.get("output_dir") or "").strip() or _default_output_dir()
        interval = int(s.get("interval") or 60)
        interval = max(10, min(3600, interval))
        nebula_path = (s.get("nebula_path") or "").strip() or _default_nebula_path()

        polling = poll_thread is not None and poll_thread.is_alive()
        start_stop_label = "Stop polling" if polling else "Start polling"
        items = [
            Item("Configure", on_configure, default=True),
            Item(start_stop_label, on_start_stop),
        ]
        if os.path.isfile(token_path) and server and server != "https://":
            items.append(Item("Nebula Commander", on_nebula_commander))
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
    try:
        tk_root.mainloop()
    except KeyboardInterrupt:
        _log("Ctrl+C received, exiting gracefully")
        stop_poll()
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
