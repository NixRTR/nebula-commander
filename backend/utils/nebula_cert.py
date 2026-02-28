"""
Wrapper for nebula-cert CLI. Runs nebula-cert subprocess for CA and cert operations.

Security: Uses subprocess with shell=False and validated arguments.
Command path is resolved at runtime but not user-controllable.
"""
import ipaddress
import logging
import re
import shutil
import subprocess  # nosec B404 - used with shell=False and validated args
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def nebula_cert_path() -> Optional[str]:
    """Return path to nebula-cert binary, or None if not found."""
    return shutil.which("nebula-cert")


# Allow only a conservative character set for arguments (hostnames, paths, identifiers).
# CodeQL: we pass the result of _to_safe_arg() to subprocess, not raw user input.
_SAFE_ARG_PATTERN = re.compile(r"^[a-zA-Z0-9_\-.:/]*$")
_ALLOWED_ARG_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.:/"
)


def _validate_arg(arg: str) -> None:
    """
    Validate subprocess argument for safety.

    While shell=False protects us from shell injection, this provides
    defense in depth by rejecting arguments with suspicious characters
    and enforcing a conservative allowlist for argument contents.
    """
    # Check for shell metacharacters that should never appear in nebula-cert args
    dangerous_chars = ['|', '&', ';', '`', '$', '(', ')', '<', '>', '\n', '\r']
    arg_str = str(arg)

    for char in dangerous_chars:
        if char in arg_str:
            raise ValueError(f"Invalid character '{char}' in argument: {arg_str[:50]}")

    # Additional check: reject null bytes
    if '\x00' in arg_str:
        raise ValueError(f"Null byte in argument: {arg_str[:50]}")

    # Enforce a reasonable maximum length to avoid abuse
    if len(arg_str) > 256:
        raise ValueError(f"Argument too long (>{256} chars): {arg_str[:50]}")

    # Allow only a conservative character set in arguments derived from user input.
    # This includes alphanumerics and a few safe punctuation characters commonly used
    # in hostnames, file paths, and identifiers.
    if not _SAFE_ARG_PATTERN.match(arg_str):
        raise ValueError(f"Argument contains disallowed characters: {arg_str[:50]}")


def _to_safe_arg(arg: str) -> str:
    """
    Validate argument and return a new string built only from allowlisted characters.
    The returned value is safe to pass to subprocess (no raw user input is passed through).
    """
    _validate_arg(arg)
    # Reconstruct from allowlist so the value passed to subprocess is not the raw input
    return "".join(c for c in str(arg) if c in _ALLOWED_ARG_CHARS)


def run_nebula_cert(args: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """
    Run nebula-cert with given args. Raises CalledProcessError on failure; stderr is logged.
    
    Security: Validates all arguments before execution to prevent injection attacks.
    """
    cmd = nebula_cert_path()
    if not cmd:
        raise FileNotFoundError("nebula-cert not found in PATH")
    
    # Pass only allowlist-derived strings to subprocess (no raw user input)
    safe_args = [_to_safe_arg(a) for a in args]
    try:
        return subprocess.run(  # nosec B603 - command path validated, shell=False, args from _to_safe_arg
            [cmd] + safe_args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as e:
        if e.stderr:
            logger.error("nebula-cert stderr: %s", e.stderr.strip())
        raise


def keygen(out_pub: Path, out_key: Path) -> None:
    """Generate a Nebula host keypair. Creates out_pub and out_key."""
    out_pub.parent.mkdir(parents=True, exist_ok=True)
    out_key.parent.mkdir(parents=True, exist_ok=True)
    run_nebula_cert([
        "keygen",
        "-out-pub", str(out_pub),
        "-out-key", str(out_key),
    ])
    logger.info("Generated keypair: %s, %s", out_pub, out_key)


def ca_generate(
    name: str,
    out_crt: Path,
    out_key: Path,
    duration_hours: int = 8760 * 2,  # 2 years
) -> None:
    """Generate a new Nebula CA. Creates out_crt and out_key."""
    out_crt.parent.mkdir(parents=True, exist_ok=True)
    out_key.parent.mkdir(parents=True, exist_ok=True)
    run_nebula_cert([
        "ca",
        "-name", name,
        "-out-crt", str(out_crt),
        "-out-key", str(out_key),
        "-duration", f"{duration_hours}h",
    ])
    logger.info("Generated CA: %s", out_crt)


def cert_sign(
    ca_crt: Path,
    ca_key: Path,
    name: str,
    ip: str,
    out_crt: Path,
    groups: Optional[list[str]] = None,
    duration_hours: int = 8760,  # 1 year
    in_pub: Optional[Path] = None,
    subnet_cidr: Optional[str] = None,
) -> None:
    """
    Sign a host certificate. If in_pub is set, sign the given public key (betterkeys).
    Otherwise nebula-cert will generate a keypair and we only get the cert (not recommended).
    -ip is passed as CIDR. Use subnet_cidr (e.g. 10.100.0.0/24) so the cert uses the network's
    prefix length; that gives hosts "vpnNetworks in common" and allows layer-3 traffic between them.
    """
    out_crt.parent.mkdir(parents=True, exist_ok=True)
    # Strip any existing /suffix from ip so we control the prefix
    ip_base = ip.split("/")[0].strip()
    if subnet_cidr:
        net = ipaddress.ip_network(subnet_cidr.strip(), strict=False)
        ip_cidr = f"{ip_base}/{net.prefixlen}"
    else:
        ip_cidr = ip if "/" in ip else f"{ip_base}/32"
    args = [
        "sign",
        "-ca-crt", str(ca_crt),
        "-ca-key", str(ca_key),
        "-name", name,
        "-ip", ip_cidr,
        "-out-crt", str(out_crt),
        "-duration", f"{duration_hours}h",
    ]
    if groups:
        args.extend(["-groups", ",".join(groups)])
    if in_pub is not None:
        args.extend(["-in-pub", str(in_pub)])
    run_nebula_cert(args)
    logger.info("Signed certificate for %s at %s", name, out_crt)
