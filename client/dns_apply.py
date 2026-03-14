"""
Split-horizon DNS apply/remove for ncclient.
Linux: systemd-resolved drop-in. Windows: NRPT (Name Resolution Policy Table).
Exposes apply() and remove() for use by run_poll_loop.

Windows NRPT testing: nslookup uses the default DNS server directly and bypasses NRPT.
To verify split-horizon, use: Resolve-DnsName <host>.nebula.example.com
or: ping <host>.nebula.example.com (uses system resolver, which respects NRPT).
"""
import json
import os
import subprocess
import sys

# When calling systemctl, avoid passing PyInstaller lib path (same as ncclient)
_SYSTEM_LIBRARY_ENV_STRIP = ("LD_LIBRARY_PATH", "LD_PRELOAD", "LD_AUDIT", "LIBPATH")


def _env_for_system_binaries():
    env = os.environ.copy()
    for key in _SYSTEM_LIBRARY_ENV_STRIP:
        env.pop(key, None)
    return env

# Fixed rule/drop-in name for idempotent remove
LINUX_DROPIN = "/etc/systemd/resolved.conf.d/nebula-dns.conf"
NRPT_RULE_NAME = "NebulaCommander"

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


def _apply_linux(domain: str, dns_servers: list[str]) -> bool:
    # Domains=~domain and DNS=ip [ip ...]. Drop-in dir must exist.
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
        subprocess.run(
            ["systemctl", "restart", "systemd-resolved"],
            check=True,
            capture_output=True,
            timeout=30,
            env=_env_for_system_binaries(),
        )
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"Failed to apply split-horizon DNS: {e}", file=sys.stderr)
        return False


def _remove_linux() -> bool:
    try:
        if os.path.isfile(LINUX_DROPIN):
            os.remove(LINUX_DROPIN)
        subprocess.run(
            ["systemctl", "restart", "systemd-resolved"],
            check=True,
            capture_output=True,
            timeout=30,
            env=_env_for_system_binaries(),
        )
        return True
    except OSError:
        # No file is fine
        try:
            subprocess.run(
                ["systemctl", "restart", "systemd-resolved"],
                check=True,
                capture_output=True,
                timeout=30,
                env=_env_for_system_binaries(),
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print(f"Failed to remove split-horizon DNS: {e}", file=sys.stderr)
        return False


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
