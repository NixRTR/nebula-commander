"""
Whether the Nebula tunnel actually carries traffic, for local status UIs.

The service's own status ("connected") only means a config was written and
Nebula restarted. This module looks at the tunnel itself: the tun device's
overlay address, and a ping to each lighthouse's overlay IP. Lighthouses get
an allow-all inbound firewall in Nebula Commander's generated config
(backend/services/config_generator.py), so a missing reply means the tunnel
is down rather than ICMP being filtered.

Used by the Windows pipe command get_connectivity (pipe_server.py).
"""
from __future__ import annotations

import os
import re
import subprocess  # nosec B404 - fixed commands only, shell=False
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import yaml

DEFAULT_TUN_DEV = "nebula1"

_RTT = re.compile(r"(?:time|Zeit|temps|tiempo)[=<]\s*([\d.]+)\s*ms", re.IGNORECASE)


def parse_config(config_yaml: str) -> tuple[str, list[str]]:
    """(tun device, lighthouse overlay IPs) from Nebula's config.yaml."""
    try:
        cfg = yaml.safe_load(config_yaml) or {}
    except yaml.YAMLError:
        return DEFAULT_TUN_DEV, []
    if not isinstance(cfg, dict):
        return DEFAULT_TUN_DEV, []
    tun = cfg.get("tun") if isinstance(cfg.get("tun"), dict) else {}
    dev = str(tun.get("dev") or DEFAULT_TUN_DEV)
    lighthouse = cfg.get("lighthouse") if isinstance(cfg.get("lighthouse"), dict) else {}
    hosts = lighthouse.get("hosts") or []
    return dev, [str(h) for h in hosts if h] if isinstance(hosts, list) else []


def interface_ipv4(dev: str) -> str | None:
    """IPv4 address on the tun device, or None if it doesn't exist / has none."""
    # The name is embedded in a PowerShell command (-Command ignores trailing
    # arguments, so there is no $args); only allow plain interface names.
    if not re.fullmatch(r"[A-Za-z0-9 ._-]{1,64}", dev):
        return None
    try:
        if sys.platform == "win32":
            out = subprocess.run(  # nosec B603 B607 - fixed argv; dev validated above
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                 f"Get-NetIPAddress -InterfaceAlias '{dev}' -AddressFamily IPv4 -ErrorAction SilentlyContinue"
                 " | Select-Object -First 1 -ExpandProperty IPAddress"],
                capture_output=True, text=True, timeout=15,
            ).stdout.strip()
        else:
            out = subprocess.run(  # nosec B603 B607
                ["ip", "-4", "-o", "addr", "show", "dev", dev],
                capture_output=True, text=True, timeout=5,
            ).stdout
            m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
            out = m.group(1) if m else ""
    except (subprocess.SubprocessError, OSError):
        return None
    return out if re.fullmatch(r"\d+\.\d+\.\d+\.\d+", out or "") else None


def ping(ip: str) -> float | None:
    """Round-trip time in ms, or None if there was no reply."""
    cmd = ["ping", "-n", "1", "-w", "1500", ip] if sys.platform == "win32" else ["ping", "-c", "1", "-W", "2", ip]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=6)  # nosec B603 - fixed argv
    except (subprocess.SubprocessError, OSError):
        return None
    if result.returncode != 0:
        return None
    m = _RTT.search(result.stdout)
    return float(m.group(1)) if m else 0.0


def get_connectivity(output_dir: str) -> dict:
    """
    {overlay_ip, interface_up, tun_dev, lighthouses: [{overlay_ip, reachable, rtt_ms}], checked_at}.
    Lighthouses are pinged in parallel so the call stays within a few seconds.
    """
    try:
        with open(os.path.join(output_dir, "config.yaml"), "r", encoding="utf-8") as f:
            dev, lighthouses = parse_config(f.read())
    except OSError:
        dev, lighthouses = DEFAULT_TUN_DEV, []

    overlay_ip = interface_ipv4(dev)
    results = []
    if overlay_ip and lighthouses:
        with ThreadPoolExecutor(max_workers=min(8, len(lighthouses))) as pool:
            rtts = list(pool.map(ping, lighthouses))
        results = [
            {"overlay_ip": ip, "reachable": rtt is not None, "rtt_ms": None if rtt is None else round(rtt)}
            for ip, rtt in zip(lighthouses, rtts)
        ]
    return {
        "overlay_ip": overlay_ip,
        "interface_up": overlay_ip is not None,
        "tun_dev": dev,
        "lighthouses": results,
        "checked_at": int(time.time()),
    }
