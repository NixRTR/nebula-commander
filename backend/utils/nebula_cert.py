"""
Wrapper for nebula-cert CLI. Runs nebula-cert subprocess for CA and cert operations.
"""
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def nebula_cert_path() -> Optional[str]:
    """Return path to nebula-cert binary, or None if not found."""
    return shutil.which("nebula-cert")


def run_nebula_cert(args: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Run nebula-cert with given args. Raises CalledProcessError on failure; stderr is logged."""
    cmd = nebula_cert_path()
    if not cmd:
        raise FileNotFoundError("nebula-cert not found in PATH")
    try:
        return subprocess.run(
            [cmd] + args,
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
) -> None:
    """
    Sign a host certificate. If in_pub is set, sign the given public key (betterkeys).
    Otherwise nebula-cert will generate a keypair and we only get the cert (not recommended).
    Uses -ca-crt/-ca-key/-networks (nebula-cert v2); -networks expects CIDR e.g. 10.100.0.1/32.
    """
    out_crt.parent.mkdir(parents=True, exist_ok=True)
    # nebula-cert sign: -ca-crt/-ca-key; -ip requires CIDR (e.g. 10.100.0.1/32)
    ip_cidr = ip if "/" in ip else f"{ip}/32"
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
