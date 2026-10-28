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
            try:
                return _windows_interface_ipv4(dev)
            except OSError:
                pass  # fall back to PowerShell (seconds, not milliseconds)
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


def _windows_interface_ipv4(dev: str) -> str | None:
    """IPv4 address of the adapter whose friendly name is dev, via GetAdaptersAddresses:
    milliseconds, where a PowerShell Get-NetIPAddress takes about a second - so
    list_networks can look addresses up live on every call. Raises OSError if the API
    call itself fails."""
    import ctypes
    from ctypes import wintypes

    class SOCKADDR_IN(ctypes.Structure):
        _fields_ = [("family", ctypes.c_ushort), ("port", ctypes.c_ushort), ("addr", ctypes.c_ubyte * 4)]

    class SOCKET_ADDRESS(ctypes.Structure):
        _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int)]

    class UNICAST(ctypes.Structure):
        pass

    UNICAST._fields_ = [("Length", wintypes.ULONG), ("Flags", wintypes.DWORD),
                        ("Next", ctypes.POINTER(UNICAST)), ("Address", SOCKET_ADDRESS)]

    class ADAPTER(ctypes.Structure):  # leading fields of IP_ADAPTER_ADDRESSES only
        pass

    ADAPTER._fields_ = [("Length", wintypes.ULONG), ("IfIndex", wintypes.DWORD),
                        ("Next", ctypes.POINTER(ADAPTER)), ("AdapterName", ctypes.c_char_p),
                        ("FirstUnicastAddress", ctypes.POINTER(UNICAST)),
                        ("FirstAnycastAddress", ctypes.c_void_p), ("FirstMulticastAddress", ctypes.c_void_p),
                        ("FirstDnsServerAddress", ctypes.c_void_p), ("DnsSuffix", ctypes.c_wchar_p),
                        ("Description", ctypes.c_wchar_p), ("FriendlyName", ctypes.c_wchar_p)]

    af_inet = 2
    flags = 0x2 | 0x4 | 0x8  # GAA_FLAG_SKIP_ANYCAST | SKIP_MULTICAST | SKIP_DNS_SERVER
    get_adapters = ctypes.WinDLL("iphlpapi.dll").GetAdaptersAddresses
    size = wintypes.ULONG(16 * 1024)
    for _ in range(3):
        buf = ctypes.create_string_buffer(size.value)
        rc = get_adapters(af_inet, flags, None, buf, ctypes.byref(size))
        if rc == 0:
            break
        if rc == 232:  # ERROR_NO_DATA: no IPv4 adapters at all
            return None
        if rc != 111:  # ERROR_BUFFER_OVERFLOW: retry with the size it asked for
            raise OSError(f"GetAdaptersAddresses failed: {rc}")
    else:
        raise OSError("GetAdaptersAddresses: buffer kept growing")

    adapter = ctypes.cast(buf, ctypes.POINTER(ADAPTER))
    while adapter:
        if (adapter.contents.FriendlyName or "").lower() == dev.lower():
            unicast = adapter.contents.FirstUnicastAddress
            while unicast:
                sa = unicast.contents.Address
                if sa.lpSockaddr and sa.iSockaddrLength >= ctypes.sizeof(SOCKADDR_IN):
                    sin = ctypes.cast(sa.lpSockaddr, ctypes.POINTER(SOCKADDR_IN)).contents
                    if sin.family == af_inet:
                        return ".".join(str(b) for b in sin.addr)
                unicast = unicast.contents.Next
            return None
        adapter = adapter.contents.Next
    return None


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
