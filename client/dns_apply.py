"""
Split-horizon DNS apply/remove for ncclient.
Linux: tries systemd-resolved, dnsmasq, NetworkManager, systemd-networkd (with resolved),
then /etc/resolv.conf (best-effort, no guaranteed split-horizon). See module doc and
_apply_linux for backend order.
Windows: NRPT (Name Resolution Policy Table).

Windows NRPT testing: nslookup uses the default DNS server directly and bypasses NRPT.
To verify split-horizon, use: Resolve-DnsName <host>.nebula.example.com
or: ping <host>.nebula.example.com (uses system resolver, which respects NRPT).
"""
import json
import os
import shutil
import subprocess
import sys

# When calling systemctl, avoid passing PyInstaller lib path (same as ncclient)
_SYSTEM_LIBRARY_ENV_STRIP = ("LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT", "LIBPATH")

# Linux paths for idempotent apply/remove
LINUX_DROPIN = "/etc/systemd/resolved.conf.d/nebula-dns.conf"
LINUX_DNSMASQ_CONF = "/etc/dnsmasq.d/nebula-commander.conf"
LINUX_NETWORKD_NETWORK = "/etc/systemd/network/70-nebula-commander.network"
LINUX_RESOLV_CONF = "/etc/resolv.conf"
LINUX_RESOLV_BACKUP = "/etc/resolv.conf.nebula-commander.bak"
RESOLV_MARKER = "# nebula-commander"

NRPT_RULE_NAME = "NebulaCommander"


def _env_for_system_binaries():
    env = os.environ.copy()
    for key in _SYSTEM_LIBRARY_ENV_STRIP:
        env.pop(key, None)
    return env

# Get rule names (GUIDs) via CIM; remove via Remove-DnsClientNrptRule (CIM delete doesn't work for this class).
# One Remove-DnsClientNrptRule per invocation to avoid pipeline/EndProcessing prompt in -NonInteractive.


def _can_apply() -> bool:
    """True if we have privileges to apply (root on Linux, elevated on Windows)."""
    if sys.platform == "win32":
        try:
            from client.ncclient import is_process_elevated
            return is_process_elevated()
        except Exception:
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return True


def _elevation_message() -> str:
    if sys.platform == "win32":
        return "Run as Administrator to apply DNS with --accept-dns, or run the contrib script manually: contrib/dns-apply-windows.ps1"
    return "Run as root to apply DNS with --accept-dns, or run the contrib script manually: contrib/dns-apply-linux.sh"


def apply_split_horizon_dns(config_path: str | None = None, config_dict: dict | None = None) -> bool:
    """
    Apply split-horizon DNS from dns-client.json path or from a dict.
    config_path: path to dns-client.json (read and parsed).
    config_dict: optional {"domain": str, "dns_servers": list[str]} (overrides config_path if both set).
    Returns True if applied, False if skipped (no config, no privilege, or error).
    """
    if not _can_apply():
        print(_elevation_message(), file=sys.stderr)
        return False

    data = config_dict
    if data is None and config_path and os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
    if not data or not isinstance(data.get("domain"), str):
        return False
    domain = (data.get("domain") or "").strip()
    servers = data.get("dns_servers") or []
    if not domain or not servers:
        return False
    servers = [s.strip() for s in servers if isinstance(s, str) and s.strip()]

    if sys.platform == "win32":
        return _apply_windows(domain, servers)
    return _apply_linux(domain, servers)


def remove_split_horizon_dns() -> bool:
    """
    Remove split-horizon DNS (drop-in or NRPT rule).
    Returns True if removed or already absent, False if no privilege or error.
    """
    if not _can_apply():
        return False
    if sys.platform == "win32":
        return _remove_windows()
    return _remove_linux()


def _run_systemctl(*args: str) -> bool:
    try:
        subprocess.run(
            ["systemctl", *args],
            check=True,
            capture_output=True,
            timeout=30,
            env=_env_for_system_binaries(),
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _linux_resolved_available() -> bool:
    return _run_systemctl("is-active", "systemd-resolved")


def _linux_dnsmasq_available() -> bool:
    if os.path.isdir("/etc/dnsmasq.d") and shutil.which("dnsmasq"):
        return True
    return _run_systemctl("is-active", "dnsmasq")


def _linux_networkmanager_available() -> bool:
    if not shutil.which("nmcli"):
        return False
    try:
        r = subprocess.run(
            ["nmcli", "-t", "-f", "RUNNING", "general"],
            capture_output=True,
            timeout=5,
            env=_env_for_system_binaries(),
        )
        return r.returncode == 0 and (r.stdout or b"").strip() == b"running"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _linux_resolv_conf_fallback_ok() -> bool:
    if not os.path.exists(LINUX_RESOLV_CONF):
        return False
    try:
        real = os.path.realpath(LINUX_RESOLV_CONF)
        if "/systemd/resolve/" in real or "/NetworkManager/" in real:
            return False
    except OSError:
        pass
    return True


def _linux_resolved_apply(domain: str, dns_servers: list[str]) -> bool:
    try:
        dropin_dir = os.path.dirname(LINUX_DROPIN)
        os.makedirs(dropin_dir, mode=0o755, exist_ok=True)
        dns_line = " ".join(dns_servers)
        content = f"""[Resolve]
Domains=~{domain}
DNS={dns_line}
"""
        with open(LINUX_DROPIN, "w", encoding="utf-8") as f:
            f.write(content)
        return _run_systemctl("restart", "systemd-resolved")
    except OSError:
        return False


def _linux_resolved_remove() -> None:
    try:
        if os.path.isfile(LINUX_DROPIN):
            os.remove(LINUX_DROPIN)
    except OSError:
        pass
    _run_systemctl("restart", "systemd-resolved")


def _linux_dnsmasq_apply(domain: str, dns_servers: list[str]) -> bool:
    try:
        os.makedirs(os.path.dirname(LINUX_DNSMASQ_CONF), mode=0o755, exist_ok=True)
        lines = [f"# Split-horizon for Nebula Commander domain {domain}"]
        for ip in dns_servers:
            lines.append(f"server=/.{domain}/{ip}")
        with open(LINUX_DNSMASQ_CONF, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        if _run_systemctl("restart", "dnsmasq"):
            return True
        r = subprocess.run(
            ["service", "dnsmasq", "restart"],
            capture_output=True,
            timeout=15,
            env=_env_for_system_binaries(),
        )
        return r.returncode == 0
    except OSError:
        return False


def _linux_dnsmasq_remove() -> None:
    try:
        if os.path.isfile(LINUX_DNSMASQ_CONF):
            os.remove(LINUX_DNSMASQ_CONF)
    except OSError:
        pass
    _run_systemctl("restart", "dnsmasq")
    subprocess.run(["service", "dnsmasq", "restart"], capture_output=True, timeout=15, env=_env_for_system_binaries())


def _linux_nebula_interface() -> str | None:
    """Return Nebula interface name (e.g. nebula0) if found."""
    try:
        r = subprocess.run(
            ["ip", "-o", "link", "show"],
            capture_output=True,
            timeout=5,
            text=True,
            env=_env_for_system_binaries(),
        )
        if r.returncode != 0:
            return None
        for line in (r.stdout or "").strip().splitlines():
            parts = line.split(":", 2)
            if len(parts) >= 3 and "nebula" in parts[1].lower():
                return parts[1].strip()
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


def _linux_networkmanager_apply(domain: str, dns_servers: list[str]) -> bool:
    iface = _linux_nebula_interface()
    if not iface:
        return False
    try:
        r = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"],
            capture_output=True,
            timeout=5,
            text=True,
            env=_env_for_system_binaries(),
        )
        if r.returncode != 0:
            return False
        conn_name = None
        for line in (r.stdout or "").strip().splitlines():
            if ":" in line:
                name, device = line.split(":", 1)
                if device.strip() == iface:
                    conn_name = name.strip()
                    break
        if not conn_name:
            r2 = subprocess.run(
                ["nmcli", "connection", "add", "type", "ethernet", "con-name", "nebula-commander", "ifname", iface, "ipv4.method", "auto"],
                capture_output=True,
                timeout=10,
                env=_env_for_system_binaries(),
            )
            if r2.returncode != 0:
                return False
            conn_name = "nebula-commander"
        dns_str = " ".join(dns_servers)
        subprocess.run(
            ["nmcli", "connection", "modify", conn_name, "ipv4.dns", dns_str, "ipv4.dns-search", domain],
            check=True,
            capture_output=True,
            timeout=10,
            env=_env_for_system_binaries(),
        )
        subprocess.run(
            ["nmcli", "connection", "reload", conn_name],
            capture_output=True,
            timeout=5,
            env=_env_for_system_binaries(),
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _linux_networkmanager_remove() -> None:
    iface = _linux_nebula_interface()
    if not iface:
        return
    try:
        r = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,DEVICE", "connection", "show", "--active"],
            capture_output=True,
            timeout=5,
            text=True,
            env=_env_for_system_binaries(),
        )
        if r.returncode != 0:
            return
        for line in (r.stdout or "").strip().splitlines():
            if ":" in line:
                name, device = line.split(":", 1)
                if device.strip() == iface:
                    subprocess.run(
                        ["nmcli", "connection", "modify", name.strip(), "ipv4.dns", "", "ipv4.dns-search", ""],
                        capture_output=True,
                        timeout=5,
                        env=_env_for_system_binaries(),
                    )
                    break
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pass


def _linux_networkd_apply(domain: str, dns_servers: list[str]) -> bool:
    if not _linux_resolved_available():
        return False
    try:
        os.makedirs(os.path.dirname(LINUX_NETWORKD_NETWORK), mode=0o755, exist_ok=True)
        dns_line = " ".join(dns_servers)
        content = f"""[Match]
Name=nebula*

[Network]
Domains=~{domain}
DNS={dns_line}
"""
        with open(LINUX_NETWORKD_NETWORK, "w", encoding="utf-8") as f:
            f.write(content)
        return _run_systemctl("restart", "systemd-networkd")
    except OSError:
        return False


def _linux_networkd_remove() -> None:
    try:
        if os.path.isfile(LINUX_NETWORKD_NETWORK):
            os.remove(LINUX_NETWORKD_NETWORK)
    except OSError:
        pass
    _run_systemctl("restart", "systemd-networkd")


def _linux_resolv_conf_apply(domain: str, dns_servers: list[str]) -> bool:
    try:
        content = ""
        if os.path.isfile(LINUX_RESOLV_CONF):
            with open(LINUX_RESOLV_CONF, "r", encoding="utf-8") as f:
                content = f.read()
        with open(LINUX_RESOLV_BACKUP, "w", encoding="utf-8") as f:
            f.write(content)
        block = f"\n{RESOLV_MARKER}\nsearch {domain}\n"
        for ip in dns_servers:
            block += f"nameserver {ip}\n"
        if not content.endswith("\n"):
            content += "\n"
        with open(LINUX_RESOLV_CONF, "w", encoding="utf-8") as f:
            f.write(content + block)
        return True
    except OSError:
        return False


def _linux_resolv_conf_remove() -> None:
    try:
        if not os.path.isfile(LINUX_RESOLV_BACKUP):
            if os.path.isfile(LINUX_RESOLV_CONF):
                with open(LINUX_RESOLV_CONF, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                out = []
                skip = False
                for line in lines:
                    if RESOLV_MARKER in line:
                        skip = True
                        continue
                    if skip and line.strip() and (line.strip().startswith("nameserver ") or line.strip().startswith("search ")):
                        continue
                    skip = False
                    out.append(line)
                with open(LINUX_RESOLV_CONF, "w", encoding="utf-8") as f:
                    f.writelines(out)
            return
        with open(LINUX_RESOLV_BACKUP, "r", encoding="utf-8") as f:
            content = f.read()
        with open(LINUX_RESOLV_CONF, "w", encoding="utf-8") as f:
            f.write(content)
        os.remove(LINUX_RESOLV_BACKUP)
    except OSError:
        pass


def _apply_linux(domain: str, dns_servers: list[str]) -> bool:
    if _linux_resolved_apply(domain, dns_servers):
        print("Split-horizon DNS applied via systemd-resolved.", file=sys.stderr)
        return True
    if _linux_dnsmasq_available() and _linux_dnsmasq_apply(domain, dns_servers):
        print("Split-horizon DNS applied via dnsmasq.", file=sys.stderr)
        return True
    if _linux_networkmanager_available() and _linux_networkmanager_apply(domain, dns_servers):
        print("Split-horizon DNS applied via NetworkManager.", file=sys.stderr)
        return True
    if _linux_resolved_available() and _linux_networkd_apply(domain, dns_servers):
        print("Split-horizon DNS applied via systemd-networkd.", file=sys.stderr)
        return True
    if _linux_resolv_conf_fallback_ok() and _linux_resolv_conf_apply(domain, dns_servers):
        print("Split-horizon DNS applied via /etc/resolv.conf (limited; not true split-horizon).", file=sys.stderr)
        print("Install systemd-resolved or dnsmasq for proper split-horizon DNS.", file=sys.stderr)
        return True
    print("Failed to apply split-horizon DNS: no backend succeeded (tried resolved, dnsmasq, NetworkManager, networkd, resolv.conf).", file=sys.stderr)
    return False


def _remove_linux() -> bool:
    _linux_resolved_remove()
    _linux_dnsmasq_remove()
    _linux_networkmanager_remove()
    _linux_networkd_remove()
    _linux_resolv_conf_remove()
    return True


def _apply_windows(domain: str, dns_servers: list[str]) -> bool:
    # NRPT: namespace with leading dot. Rule name fixed for idempotent remove.
    if not dns_servers:
        return False
    namespace = f".{domain}" if not domain.startswith(".") else domain
    # PowerShell: -DisplayName (friendly name), -NameServers (DNS servers). -Name is not a valid Add parameter.
    # Remove each NebulaCommander rule by its .Name (GUID) so all old namespaces are cleared.
    # Remove via Remove-DnsClientNrptRule -Name (CIM delete doesn't work for NRPT).
    addrs = ",".join(f"'{s}'" for s in dns_servers)
    _remove_windows()
    ps_add = f"""
$ErrorActionPreference = 'Stop'
$ConfirmPreference = 'None'
Add-DnsClientNrptRule -Namespace '{namespace}' -DisplayName '{NRPT_RULE_NAME}' -NameServers @({addrs}) -Confirm:$false
"""
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_add],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"Failed to apply NRPT: {e}", file=sys.stderr)
        if e.stderr:
            print(e.stderr.decode(errors="replace"), file=sys.stderr)
        return False


def _remove_windows() -> bool:
    # Same loop as manual cleanup: Get-DnsClientNrptRule + Remove-DnsClientNrptRule -Name.
    # Run without -NonInteractive so Remove-DnsClientNrptRule doesn't hit "Read and Prompt" (fails when tray exits).
    ps = f"""
$ErrorActionPreference = 'Stop'
$ConfirmPreference = 'None'
$RuleName = '{NRPT_RULE_NAME}'
$max = 10
for ($i = 0; $i -lt $max; $i++) {{
  $names = @(Get-DnsClientNrptRule | Where-Object {{ $_.DisplayName -eq $RuleName }} | ForEach-Object {{ $_.Name }})
  if ($names.Count -eq 0) {{ break }}
  foreach ($n in $names) {{ Remove-DnsClientNrptRule -Name $n -Confirm:$false -Force -ErrorAction SilentlyContinue }}
}}
"""
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],  # no -NonInteractive
            check=True,
            capture_output=True,
            timeout=60,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"Failed to remove NRPT rule: {e}", file=sys.stderr)
        if getattr(e, "stderr", None):
            print(e.stderr.decode(errors="replace"), file=sys.stderr)
        return False
