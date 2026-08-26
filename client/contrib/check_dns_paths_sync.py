#!/usr/bin/env python3
"""
Coarse drift check between client/dns_apply.py (the real split-horizon DNS implementation)
and its two manual fallback scripts, contrib/dns-apply-linux.sh and
contrib/dns-apply-windows.ps1 (for when ncclient lacks privilege to self-apply DNS).

Those scripts hand-duplicate a handful of path/marker constants from dns_apply.py. This
doesn't try to verify behavior, just that a path/marker changed in dns_apply.py hasn't been
silently forgotten in the corresponding script. Run from anywhere; paths are resolved
relative to this file.

Exit 0: all checked constants still appear in their sibling script(s).
Exit 1: at least one has drifted - update the listed file(s) and re-run.
"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, os.path.dirname(CLIENT_DIR))

from client import dns_apply  # noqa: E402

LINUX_SH = os.path.join(SCRIPT_DIR, "dns-apply-linux.sh")
WINDOWS_PS1 = os.path.join(SCRIPT_DIR, "dns-apply-windows.ps1")

# (constant name, value, sibling script) - only the constants the fallback scripts actually
# mirror. LINUX_NETWORKD_NETWORK is intentionally excluded: dns-apply-linux.sh only covers
# systemd-resolved/dnsmasq/resolv.conf, not systemd-networkd or NetworkManager.
CHECKS = [
    ("LINUX_DROPIN", dns_apply.LINUX_DROPIN, LINUX_SH),
    ("LINUX_DNSMASQ_CONF", dns_apply.LINUX_DNSMASQ_CONF, LINUX_SH),
    ("LINUX_RESOLV_CONF", dns_apply.LINUX_RESOLV_CONF, LINUX_SH),
    ("LINUX_RESOLV_BACKUP", dns_apply.LINUX_RESOLV_BACKUP, LINUX_SH),
    ("RESOLV_MARKER", dns_apply.RESOLV_MARKER, LINUX_SH),
    ("NRPT_RULE_NAME", dns_apply.NRPT_RULE_NAME, WINDOWS_PS1),
]


def main() -> int:
    failures = []
    for name, value, script_path in CHECKS:
        with open(script_path, "r", encoding="utf-8") as f:
            contents = f.read()
        if value not in contents:
            failures.append(
                f"{name} = {value!r} (from client/dns_apply.py) not found in {os.path.basename(script_path)}"
            )

    if failures:
        print("DNS path/marker drift detected between dns_apply.py and its fallback scripts:")
        for line in failures:
            print(f"  - {line}")
        return 1

    print(f"OK: {len(CHECKS)} constants all present in their sibling script(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
