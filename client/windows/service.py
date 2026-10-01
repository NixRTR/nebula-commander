"""
Nebula Commander Windows Service.

Runs client.ncclient.run_poll_loop() as LocalSystem, so launching Nebula and
applying split-horizon DNS have full privilege without any UAC prompt. Owns
all state under %ProgramData%\\nebula-commander\\ (SYSTEM/Administrators-only)
and hosts the named-pipe API (pipe_server.py) that the GUI (client/windows-app/)
uses for every read and change - changes require an elevated administrator.
Runs only its own checksum-verified Nebula install (nebula_install.py).

Installed/managed via the MSI (installer/windows/Product.wxs's ServiceInstall/
ServiceControl elements) - this module does not register itself as part of the
supported install flow. For manual/dev use, pywin32 still provides this for free:
  python -m client.windows.service install|remove|start|stop|debug
"""
from __future__ import annotations

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
from client.windows.shared_paths import enable_shared_mode, load_status, save_status, shared_root  # noqa: E402

enable_shared_mode()

import servicemanager  # noqa: E402
import win32event  # noqa: E402
import win32service  # noqa: E402
import win32serviceutil  # noqa: E402

from client.config import load_settings, save_settings  # noqa: E402
from client.ncclient import run_poll_loop  # noqa: E402
from client.windows import nebula_install  # noqa: E402
from client.windows.harden import harden_shared_root  # noqa: E402
from client.windows.pipe_server import PipeServer, ServiceHooks  # noqa: E402


def _drop_legacy_nebula_path() -> None:
    """Older versions honored settings.json's nebula_path - and that file was
    writable by every local user. Strip it so nothing ever reads it again."""
    settings = load_settings()
    if "nebula_path" in settings:
        settings.pop("nebula_path", None)
        save_settings(settings)


class NebulaCommanderService(win32serviceutil.ServiceFramework, ServiceHooks):
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
        # Serializes poll-loop restarts and Nebula updates - pipe commands are
        # served on concurrent threads.
        self.control_lock = threading.Lock()

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
        # Always the service-managed, checksum-verified install - never a
        # caller-supplied path (see nebula_install's module docstring).
        nebula_path = nebula_install.nebula_exe_path()
        accept_dns = bool(settings.get("accept_dns", False))
        output_dir = shared_root()

        if not server:
            save_status("error", "Set server URL from the Nebula Commander app's Settings page")
            return
        if not os.path.isfile(nebula_path):
            save_status("error", "Nebula is not installed - use Settings > Nebula > Install in the app")
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

    def _stop_poll(self) -> None:
        self.stop_event.set()
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=15)

    def _restart_poll_locked(self) -> None:
        self._stop_poll()
        self._start_poll()

    # --- ServiceHooks (called from pipe_server threads) ---

    def restart_poll(self) -> None:
        """Stop the current poll loop and start a fresh one, which re-reads
        settings.json immediately instead of waiting up to `interval` seconds."""
        with self.control_lock:
            self._restart_poll_locked()

    def update_nebula(self, tag: "str | None") -> str:
        """Download + verify + stage while Nebula keeps running, then stop the
        poll loop (which stops nebula.exe), swap the install in, and restart."""
        with self.control_lock:
            previous = load_status()
            save_status("updating", "Downloading Nebula...")
            try:
                staged = nebula_install.prepare(tag)
            except nebula_install.NebulaInstallError:
                # Live install untouched and still running - put its status back.
                extra = {k: v for k, v in previous.items() if k not in ("state", "message", "updated_at")}
                save_status(previous.get("state", "unknown"), previous.get("message", ""), **extra)
                raise
            self._stop_poll()
            try:
                nebula_install.swap()
            finally:
                self._start_poll()
            return staged

    def _first_run_install(self) -> None:
        """No Nebula yet (fresh install, or the upgrade that removed the old
        user-writable copy): install the latest release once, in the
        background, so the service comes up on its own."""
        if os.path.isfile(nebula_install.nebula_exe_path()):
            return
        try:
            self.update_nebula(None)
        except Exception as e:
            save_status("error", f"Nebula install failed: {getattr(e, 'message', e)} - retry from the app's Settings page")

    def _run(self) -> None:
        # Before anything else reads or writes the state folder - see harden.py.
        try:
            harden_shared_root(servicemanager.LogWarningMsg)
        except Exception as e:
            servicemanager.LogErrorMsg(f"Hardening {shared_root()} failed: {e}")
        save_status("starting", "Service starting")
        _drop_legacy_nebula_path()
        self.pipe_thread = PipeServer(self, self.pipe_stop, servicemanager.LogWarningMsg)
        self.pipe_thread.start()
        with self.control_lock:
            self._start_poll()
        threading.Thread(target=self._first_run_install, name="nebula-first-install", daemon=True).start()

        win32event.WaitForSingleObject(self.win32_stop_event, win32event.INFINITE)

        with self.control_lock:
            self._stop_poll()
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
