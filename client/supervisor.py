"""
One ncclient process, several networks: runs one client.ncclient.run_poll_loop thread
per enrollment (client/config.py) and keeps that set in step with settings.json -
a network enrolled through the app, CLI, D-Bus or the Windows pipe starts within a
couple of seconds, a removed one is stopped (its Nebula, DNS and routing are undone by
the loop itself on the way out) and its directory deleted, and a network whose server
changed is restarted.

Host-wide pieces live here rather than in each loop:
- the one-time conversion of pre-0.8.0 settings (config.migrate_to_enrollments);
- Windows: stopping a nebula.exe left running by a previous service instance, once,
  before any network starts (each loop would otherwise kill the others' Nebula);
- listen ports: two networks can't bind the same UDP port. A network asking for a port
  another one already uses is moved to port 0 (the OS picks; lighthouses learn it), unless
  it's a lighthouse or relay, which peers reach at a fixed port - that one is reported;
- tun devices: two networks can't share one. Servers before 0.8.0 give every network
  the legacy nebula1 (or no tun.dev, which Nebula reads as nebula1), so a second such
  network is renamed locally to nc-<its id> - see _dev_filter;
- one status for the whole host (status_callback) on top of each network's own
  status.json, for apps and logs that show a single line.
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from client import config as cfg

__all__ = ["Supervisor"]

# The device every network got before servers set one per network (Nebula's default).
LEGACY_TUN_DEV = "nebula1"


@dataclass
class _Loop:
    thread: threading.Thread
    stop: threading.Event
    server: str
    name: str = ""
    status: tuple = field(default=("starting", "Starting"))


class Supervisor:
    def __init__(
        self,
        output_dir: str,
        interval: int,
        nebula_bin: Optional[str],
        restart_service: Optional[str],
        stop_event: threading.Event,
        accept_dns: bool = False,
        status_callback: Optional[Callable[[str, str], None]] = None,
        dns_debug_log: Optional[Callable[[str], None]] = None,
        default_server: Optional[str] = None,
        log: Optional[Callable[[str], None]] = None,
        reconcile_every: float = 2.0,
        save_network_status: Optional[Callable[[str, str, str, dict], None]] = None,
    ) -> None:
        self.output_dir = os.path.expanduser(output_dir)
        self.interval = interval
        self.nebula_bin = nebula_bin
        self.restart_service = restart_service
        self.stop_event = stop_event
        self.accept_dns = accept_dns
        self.status_callback = status_callback
        self.dns_debug_log = dns_debug_log
        self.default_server = (default_server or "").strip() or None
        self._log_fn = log
        self.reconcile_every = reconcile_every
        self._save_network_status = save_network_status or _default_save_network_status
        self._loops: dict[str, _Loop] = {}
        self._ports: dict[str, int] = {}
        self._lock = threading.Lock()
        self._last_host_status: Optional[tuple] = None

    # --- lifecycle -------------------------------------------------------------------

    def run(self) -> None:
        """Run until stop_event is set; stops every network on the way out."""
        try:
            cfg.migrate_to_enrollments(self.output_dir, self._log)
        except Exception as e:  # a failed migration must not keep the networks down
            self._log(f"Converting settings to the multi-network layout failed: {e}")
        if sys.platform == "win32" and self.nebula_bin:
            from client.ncclient import _stop_nebula
            _stop_nebula(None)
        self._remove_orphan_dirs()
        try:
            while not self.stop_event.is_set():
                self.reconcile()
                self.stop_event.wait(self.reconcile_every)
        finally:
            self.stop_all()

    def reconcile(self) -> None:
        settings = cfg.load_settings()
        wanted = {e["id"]: e for e in cfg.enrollments(settings)}
        for eid, loop in list(self._loops.items()):
            e = wanted.get(eid)
            if e is None:
                self._log(f"Network {loop.name or eid} removed; stopping it")
                self._stop(eid, remove_dir=True)
            elif self._server(e) != loop.server:
                self._log(f"Network {loop.name or eid}: server changed; restarting it")
                self._stop(eid)
            elif not loop.thread.is_alive():
                self._stop(eid)  # ended on its own - started again below
        for eid, e in wanted.items():
            if eid not in self._loops:
                self._start(e)
        if not wanted:
            self._host_status("idle", "Not enrolled in any network. Enroll to connect.")

    def stop_all(self) -> None:
        for eid in list(self._loops):
            self._stop(eid)

    # --- one network -------------------------------------------------------------------

    def _server(self, e: dict) -> Optional[str]:
        return (e.get("server") or "").strip() or self.default_server

    def _start(self, e: dict) -> None:
        from client.ncclient import run_poll_loop

        eid = e["id"]
        name = e.get("name") or eid
        server = self._server(e)
        d = cfg.enrollment_dir(self.output_dir, eid)
        os.makedirs(d, exist_ok=True)
        if not server:
            self._save_network_status(d, "error", "No server URL for this network - enroll it again", {})
            return
        stop = threading.Event()
        loop = _Loop(thread=None, stop=stop, server=server, name=name)  # type: ignore[arg-type]
        loop.thread = threading.Thread(
            target=run_poll_loop,
            args=(server, d, self.interval, self.nebula_bin, self.restart_service),
            kwargs={
                "stop_event": stop,
                "status_callback": self._network_status_callback(eid, d),
                "accept_dns": self.accept_dns,
                "dns_debug_log": self.dns_debug_log,
                "enrollment_id": eid,
                "manage_host": False,
                "config_filter": self._config_filter(eid, name),
            },
            name=f"network-{eid}",
            daemon=True,
        )
        self._loops[eid] = loop
        self._log(f"Starting network {name} ({server})")
        loop.thread.start()

    def _stop(self, eid: str, remove_dir: bool = False) -> None:
        loop = self._loops.pop(eid, None)
        if loop is not None:
            loop.stop.set()
            loop.thread.join(timeout=30)
        with self._lock:
            self._ports.pop(eid, None)
        if remove_dir:
            shutil.rmtree(cfg.enrollment_dir(self.output_dir, eid), ignore_errors=True)
        self._report_host_status()

    def _remove_orphan_dirs(self) -> None:
        """Directories of networks removed while this service wasn't running."""
        base = os.path.join(self.output_dir, "networks")
        known = {e["id"] for e in cfg.enrollments(cfg.load_settings())}
        try:
            names = os.listdir(base)
        except OSError:
            return
        for name in names:
            if name not in known and os.path.isdir(os.path.join(base, name)):
                self._log(f"Removing the directory of removed network {name}")
                shutil.rmtree(os.path.join(base, name), ignore_errors=True)

    # --- status ------------------------------------------------------------------------

    def _network_status_callback(self, eid: str, d: str) -> Callable[[str, str], None]:
        def cb(state: str, message: str) -> None:
            loop = self._loops.get(eid)
            if loop is not None:
                loop.status = (state, message)
            extra = {}
            if sys.platform == "win32" and state == "connected":
                ip = _overlay_ip(d)
                if ip:
                    extra["overlay_ip"] = ip
            try:
                self._save_network_status(d, state, message, extra)
            except OSError as e:
                self._log(f"Could not write {d}/status.json: {e}")
            self._report_host_status()
        return cb

    def _report_host_status(self) -> None:
        loops = list(self._loops.values())
        if not loops:
            return
        errors = [lp for lp in loops if lp.status[0] == "error"]
        if errors:
            state, message = "error", "; ".join(f"{lp.name}: {lp.status[1]}" for lp in errors)
        elif all(lp.status[0] == "connected" for lp in loops):
            state = "connected"
            message = loops[0].status[1] if len(loops) == 1 else f"{len(loops)} networks connected"
        else:
            state, message = loops[0].status if len(loops) == 1 else ("idle", f"{len(loops)} networks starting")
        self._host_status(state, message)

    def _host_status(self, state: str, message: str) -> None:
        if (state, message) == self._last_host_status:
            return
        self._last_host_status = (state, message)
        if self.status_callback:
            self.status_callback(state, message)

    def _config_filter(self, eid: str, name: str) -> Callable[[bytes], bytes]:
        dev_filter, port_filter = self._dev_filter(eid, name), self._port_filter(eid, name)
        return lambda config_bytes: port_filter(dev_filter(config_bytes))

    # --- tun devices -------------------------------------------------------------------

    def _dev_on_disk(self, eid: str) -> Optional[str]:
        """tun.dev of a network's config.yaml as written: LEGACY_TUN_DEV when it has none
        (what Nebula uses then), None when there's no config yet."""
        try:
            with open(os.path.join(cfg.enrollment_dir(self.output_dir, eid), "config.yaml"), "rb") as f:
                data = f.read()
        except OSError:
            return None
        from client.ncclient import _tun_dev_from_config
        return _tun_dev_from_config(data) or LEGACY_TUN_DEV

    def _dev_filter(self, eid: str, name: str) -> Callable[[bytes], bytes]:
        """Rename this network's tun device to nc-<id> when another network on this host
        has (or, for nebula1, will get) the one its server asks for.

        Deterministic, so a restart doesn't swap names: a network keeps a device it
        already has unless one earlier in settings has it too; nebula1 also goes to an
        earlier network that has no config yet (two pre-0.8.0 networks enrolled at once).
        A network renamed away from nebula1 keeps nc-<id> even after the other network is
        removed, so it isn't renamed back and forth."""
        own = f"nc-{eid}"

        def f(config_bytes: bytes) -> bytes:
            import yaml
            try:
                parsed = yaml.safe_load(config_bytes)
            except yaml.YAMLError:
                return config_bytes
            if not isinstance(parsed, dict):
                return config_bytes
            tun = parsed.get("tun") if isinstance(parsed.get("tun"), dict) else {}
            dev = tun.get("dev") if isinstance(tun.get("dev"), str) and tun.get("dev") else LEGACY_TUN_DEV
            if dev == own:
                return config_bytes
            order = [e["id"] for e in cfg.enrollments(cfg.load_settings())]
            mine = order.index(eid) if eid in order else len(order)
            on_disk = self._dev_on_disk(eid)
            holder = None
            if dev == LEGACY_TUN_DEV and on_disk == own:
                holder = ""  # renamed before: keep it
            else:
                for i, other in enumerate(order):
                    if other == eid:
                        continue
                    theirs = self._dev_on_disk(other)
                    if (theirs == dev and (on_disk != dev or i < mine)) or (
                        dev == LEGACY_TUN_DEV and theirs is None and i < mine
                    ):
                        holder = other
                        break
            if holder is None:
                return config_bytes
            if holder and on_disk != own:
                loop = self._loops.get(holder)
                self._log(f"Network {name}: tun device {dev} belongs to network "
                          f"{loop.name if loop else holder} on this host; using {own} instead")
            if not isinstance(parsed.get("tun"), dict):
                parsed["tun"] = {}
            parsed["tun"]["dev"] = own
            return yaml.safe_dump(parsed, default_flow_style=False, sort_keys=False).encode()
        return f

    # --- listen ports ------------------------------------------------------------------

    def _port_filter(self, eid: str, name: str) -> Callable[[bytes], bytes]:
        def f(config_bytes: bytes) -> bytes:
            import yaml
            try:
                parsed = yaml.safe_load(config_bytes)
            except yaml.YAMLError:
                return config_bytes
            if not isinstance(parsed, dict):
                return config_bytes
            listen = parsed.get("listen") if isinstance(parsed.get("listen"), dict) else {}
            try:
                port = int(listen.get("port", 4242))
            except (TypeError, ValueError):
                return config_bytes
            with self._lock:
                if port == 0:
                    self._ports.pop(eid, None)
                    return config_bytes
                owner = next((o for o, p in self._ports.items() if o != eid and p == port), None)
                if owner is None:
                    self._ports[eid] = port
                    return config_bytes
                self._ports.pop(eid, None)
            other = self._loops.get(owner)
            other_name = other.name if other else owner
            fixed = bool((parsed.get("lighthouse") or {}).get("am_lighthouse")) or bool(
                (parsed.get("relay") or {}).get("am_relay")
            )
            if fixed:
                self._log(f"Network {name}: listen port {port} is already used by network {other_name}, and a "
                          "lighthouse/relay needs a fixed port - give one of them another port in Nebula Commander")
                return config_bytes
            self._log(f"Network {name}: listen port {port} is already used by network {other_name}; "
                      "using a port the OS picks instead")
            parsed.setdefault("listen", {})["port"] = 0
            return yaml.safe_dump(parsed, default_flow_style=False, sort_keys=False).encode()
        return f

    def _log(self, msg: str) -> None:
        if self._log_fn:
            self._log_fn(msg)
        elif self.dns_debug_log:
            self.dns_debug_log(msg)
        else:
            print(msg, file=sys.stderr, flush=True)


def _default_save_network_status(d: str, state: str, message: str, extra: dict) -> None:
    from client.status_store import save_status
    save_status(os.path.join(d, "status.json"), state, message, **extra)


def _overlay_ip(d: str) -> Optional[str]:
    try:
        import yaml
        with open(os.path.join(d, "config.yaml"), "r", encoding="utf-8") as f:
            dev = ((yaml.safe_load(f) or {}).get("tun") or {}).get("dev") or "nebula1"
        from client.connectivity import interface_ipv4
        return interface_ipv4(str(dev))
    except Exception:
        return None
