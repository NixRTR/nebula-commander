"""
Nebula Commander Windows system-tray app. Enroll, poll for config/certs, optionally run Nebula.
Run from repo root: python -m client.windows.tray

Run with: python -m client.windows.tray  (from repo root)
Terminal output: use --console, -v, or --verbose to print log messages to stderr.
Alternatively: set NCCLIENT_TRAY_VERBOSE=1, or run from a console (stdout is a TTY).
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

from client.config import config_dir, load_settings, save_settings
from client.ncclient import (
    run_poll_loop,
    cmd_enroll,
    _default_output_dir,
    is_process_elevated,
    get_elevation_debug_info,
)
from client.token_store import get_token
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
    """Directory where we install downloaded nebula.exe: config_dir/nebula/"""
    return os.path.join(config_dir(), "nebula")


def _downloaded_nebula_path() -> str:
    """Path to nebula.exe in ~/.config/nebula-commander/nebula/ if it exists, else empty."""
    exe = os.path.join(_nebula_download_dir(), "nebula.exe")
    return exe if os.path.isfile(exe) else ""


def _default_nebula_path() -> str:
    """Default: previously downloaded exe in config dir, or 'nebula' on PATH."""
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
    # e.g. "nebula" or "nebula.exe" on PATH
    return shutil.which(path)


NEBULA_VERSION_DEFAULT = "v1.10.2"
NEBULA_URL_TEMPLATE = "https://github.com/slackhq/nebula/releases/download/{version}/nebula-windows-amd64.zip"
NEBULA_RELEASES_URL = "https://github.com/slackhq/nebula/releases"
NEBULA_API_LATEST = "https://api.github.com/repos/slackhq/nebula/releases/latest"


def _download_nebula_to_dir(version: str, dest_dir: str) -> tuple[bool, str | None, str]:
    """
    Download Nebula Windows binary and extract nebula.exe into dest_dir.
    Returns (success, path_to_exe or None, error_message).
    """
    import tempfile
    import traceback
    import urllib.request
    url = NEBULA_URL_TEMPLATE.format(version=version)
    exe_path = os.path.join(dest_dir, "nebula.exe")
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(tempfile.gettempdir(), "nebula-windows-amd64.zip")
    _log(f"Download Nebula: version={version}, url={url}, dest_dir={dest_dir}")
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


def _download_nebula_to_config(version: str) -> tuple[bool, str | None, str]:
    """
    Download Nebula Windows binary and extract to config_dir/nebula/nebula.exe.
    Returns (success, path_to_exe or None, error_message).
    """
    return _download_nebula_to_dir(version, _nebula_download_dir())


def _get_nebula_version(nebula_bin: str) -> str | None:
    """Run nebula -version (or --version) and parse version string. Returns e.g. '1.10.2' or None."""
    import re
    import subprocess
    for flag in ("-version", "--version"):
        try:
            out = subprocess.run(
                [nebula_bin, flag],
                capture_output=True,
                text=True,
                timeout=10,
            )
            text = (out.stdout or "") + (out.stderr or "")
            m = re.search(r"v?(\d+\.\d+\.\d+)", text)
            if m:
                return m.group(1)
        except Exception as e:
            _log(f"nebula {flag} failed: {e}")
    return None


def _fetch_latest_nebula_tag() -> str | None:
    """Fetch latest release tag from GitHub API. Returns e.g. 'v1.10.3' or None."""
    import urllib.request
    try:
        req = urllib.request.Request(
            NEBULA_API_LATEST,
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        tag = data.get("tag_name")
        return tag if isinstance(tag, str) and tag else None
    except Exception as e:
        _log(f"Fetch latest Nebula tag failed: {e}")
        return None


def _parse_version_tuple(version_str: str) -> tuple[int, int, int]:
    """Parse 'v1.10.2' or '1.10.2' to (1, 10, 2). Missing parts become 0."""
    import re
    m = re.search(r"v?(\d+)\.?(\d*)\.?(\d*)", (version_str or "").strip())
    if not m:
        return (0, 0, 0)
    a, b, c = m.group(1), m.group(2) or "0", m.group(3) or "0"
    return (int(a), int(b), int(c))


def _is_newer_version(local_version: str, latest_tag: str) -> bool:
    """True if latest_tag is newer than local_version (e.g. '1.10.2' vs 'v1.10.3')."""
    local_t = _parse_version_tuple(local_version)
    latest_t = _parse_version_tuple(latest_tag)
    return latest_t > local_t


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


def main() -> None:
    if sys.platform != "win32":
        print("Windows tray app is Windows-only.", file=sys.stderr)
        sys.exit(1)

    _log(f"main thread id={threading.current_thread().ident}")
    if sys.platform == "win32":
        for line in get_elevation_debug_info():
            _log(line)
        _log("Process elevated: %s" % ("Yes" if is_process_elevated() else "No"))

    settings = load_settings()
    server = (settings.get("server") or "").strip() or "https://"
    output_dir = (settings.get("output_dir") or "").strip() or _default_output_dir()
    interval = int(settings.get("interval") or 60)
    if interval < 10:
        interval = 10
    elif interval > 3600:
        interval = 3600
    nebula_path = _effective_nebula_path_from_settings(settings)

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
        # Re-read settings so tray menu has latest
        s = load_settings()
        server = (s.get("server") or "").strip() or "https://"
        output_dir = (s.get("output_dir") or "").strip() or _default_output_dir()
        interval = int(s.get("interval") or 60)
        interval = max(10, min(3600, interval))
        nebula_path = _effective_nebula_path_from_settings(s)

        if not server or server == "https://":
            update_ui("error", "Set server URL in Settings")
            return
        if get_token() is None:
            update_ui("error", "Enroll first")
            return
        # Only pass a nebula path if the binary exists or is on PATH; else poll without starting Nebula
        nebula_bin = _resolve_nebula_bin(nebula_path)
        # On Windows, Nebula must run elevated. If we're not elevated, poll config but do not start Nebula.
        no_elevation_nebula = False
        if sys.platform == "win32" and nebula_bin is not None and not is_process_elevated():
            _log("Not elevated: polling config only; Nebula will not start. Run tray as Administrator.")
            update_ui("error", "Run as Administrator for Nebula")
            nebula_bin = None
            no_elevation_nebula = True
        stop_event.clear()
        if VERBOSE:
            os.environ["NCCLIENT_NEBULA_CONSOLE"] = "1"

        def callback(s: str, m: str) -> None:
            if no_elevation_nebula and s in ("idle", "connected"):
                update_ui("error", "Run as Administrator for Nebula")
            else:
                update_ui(s, m)

        poll_thread = threading.Thread(
            target=run_poll_loop,
            args=(server, output_dir, interval, nebula_bin, None),
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
                cmd_enroll(server_url, code)
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
        s = load_settings()
        raw_nebula = (s.get("nebula_path") or "").strip()
        if dialogs._is_stale_nebula_path(raw_nebula):
            raw_nebula = ""
        result = dialogs.settings_dialog(parent, server, output_dir, interval, raw_nebula)
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

    def _do_start_poll(parent: tk.Tk | None) -> None:
        """Run nebula check/install/upgrade flow on main thread, then start polling if OK."""
        nonlocal server, output_dir, interval, nebula_path
        s = load_settings()
        server = (s.get("server") or "").strip() or "https://"
        output_dir = (s.get("output_dir") or "").strip() or _default_output_dir()
        interval = int(s.get("interval") or 60)
        interval = max(10, min(3600, interval))
        nebula_path = _effective_nebula_path_from_settings(s)

        if not server or server == "https://":
            update_ui("error", "Set server URL in Settings")
            return
        if get_token() is None:
            update_ui("error", "Enroll first")
            return

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
            default_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "nebula-commander", "bin")
            dir_path = filedialog.askdirectory(
                title="Choose install directory for Nebula",
                initialdir=default_dir if os.path.isdir(default_dir) else os.path.expanduser("~"),
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
            _add_dir_to_user_path(dir_path)
            nebula_path = exe_path
            save_settings({"server": server, "output_dir": output_dir, "interval": interval, "nebula_path": nebula_path})
            if parent:
                messagebox.showinfo(
                    "Nebula installed",
                    f"Nebula installed to:\n{exe_path}\n\nThe directory was added to your user PATH. "
                    "You may need to restart the tray or open a new terminal for it to take effect.",
                    parent=parent,
                )
            run_poll()
            if icon_obj and hasattr(icon_obj, "update_menu"):
                icon_obj.update_menu()
            return

        local_ver = _get_nebula_version(nebula_bin)
        latest_tag = _fetch_latest_nebula_tag()
        if latest_tag and local_ver and _is_newer_version(local_ver, latest_tag):
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
                    default_dir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "nebula-commander", "bin")
                    dest_dir = filedialog.askdirectory(
                        title="Choose directory for Nebula upgrade",
                        initialdir=default_dir if os.path.isdir(default_dir) else os.path.dirname(nebula_bin),
                        parent=parent,
                    )
                    if not dest_dir:
                        run_poll()
                        if icon_obj and hasattr(icon_obj, "update_menu"):
                            icon_obj.update_menu()
                        return
                ok, exe_path, err = _download_nebula_to_dir(latest_tag, dest_dir)
                if ok:
                    if dest_dir != os.path.dirname(nebula_bin):
                        _add_dir_to_user_path(dest_dir)
                    nebula_path = exe_path
                    save_settings({"server": server, "output_dir": output_dir, "interval": interval, "nebula_path": nebula_path})
                    if parent:
                        messagebox.showinfo("Nebula upgraded", f"Nebula updated to {latest_tag} at:\n{exe_path}", parent=parent)
                    if icon_obj and hasattr(icon_obj, "update_menu"):
                        icon_obj.update_menu()
                else:
                    if parent:
                        messagebox.showerror("Upgrade Nebula", err or "Download failed.", parent=parent)

        run_poll()
        if icon_obj and hasattr(icon_obj, "update_menu"):
            icon_obj.update_menu()

    def on_start_stop(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if poll_thread and poll_thread.is_alive():
            stop_poll()
            update_ui("idle", "Stopped")
        else:
            ui_queue.put("start_poll")
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

    def on_configure(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _log("on_configure: putting 'settings' in queue")
        ui_queue.put("settings")

    def on_nebula_commander(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if server and server != "https://":
            webbrowser.open(server)

    def _nebula_found() -> bool:
        effective = (nebula_path or "").strip() or _default_nebula_path()
        return _resolve_nebula_bin(effective) is not None

    def make_menu() -> pystray.Menu:
        nonlocal server, output_dir, interval, nebula_path
        # Re-read settings so tray menu has latest (e.g. server URL for Nebula Commander link)
        s = load_settings()
        server = (s.get("server") or "").strip() or "https://"
        output_dir = (s.get("output_dir") or "").strip() or _default_output_dir()
        interval = int(s.get("interval") or 60)
        interval = max(10, min(3600, interval))
        nebula_path = _effective_nebula_path_from_settings(s)

        polling = poll_thread is not None and poll_thread.is_alive()
        start_stop_label = "Stop polling" if polling else "Start polling"
        items = [
            Item("Settings", on_configure, default=True),
            Item("Enroll", on_enroll),
            Item(start_stop_label, on_start_stop),
        ]
        if get_token() is not None and server and server != "https://":
            items.append(Item("Nebula Commander", on_nebula_commander))
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
        if msg == "download_nebula":
            _do_download_nebula(tk_root)
        if msg == "start_poll":
            _do_start_poll(tk_root)
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
    # Auto-start polling when the tray starts (e.g. at login when Run On Startup is enabled)
    tk_root.after(500, lambda: ui_queue.put("start_poll"))
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
