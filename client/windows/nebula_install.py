"""
Service-managed Nebula install for Windows.

The LocalSystem service only ever runs the Nebula binary installed here, under
%ProgramData%\\nebula-commander\\nebula\\ (SYSTEM/Administrators-only, see
installer/windows/Product.wxs). It used to run whatever `nebula_path`
settings.json named, and the GUI downloaded nebula.exe into a folder every
local user could write - together that let any local user run code as SYSTEM.

Install flow (download/verify/extract happen while the current Nebula keeps
running; only swap() needs it stopped, since Windows locks a running exe):

  1. prepare(): resolve the release tag (latest unless pinned), download
     nebula-windows-<arch>.zip and the release's SHASUM256.txt, verify the
     zip's SHA256 (refuse on mismatch or a missing entry), extract the WHOLE
     archive - nebula.exe, nebula-cert.exe and dist\\ (wintun.dll, which
     nebula.exe needs at runtime) - into nebula.staging\\, then verify the
     extracted nebula.exe / nebula-cert.exe against their own SHASUM256
     entries too.
  2. swap(): replace nebula\\ with nebula.staging\\ (old copy kept as
     nebula.old\\ until the rename succeeds, then removed).
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import shutil
import tempfile
import zipfile

from client.windows.shared_paths import shared_root

__all__ = [
    "NebulaInstallError",
    "nebula_dir",
    "nebula_exe_path",
    "installed_version",
    "latest_tag",
    "prepare",
    "swap",
]

_API_LATEST = "https://api.github.com/repos/slackhq/nebula/releases/latest"
_DOWNLOAD = "https://github.com/slackhq/nebula/releases/download/{tag}/{name}"
_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
_HTTP_TIMEOUT = 60
_USER_AGENT = "NebulaCommanderService"


class NebulaInstallError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def nebula_dir() -> str:
    return os.path.join(shared_root(), "nebula")


def _staging_dir() -> str:
    return os.path.join(shared_root(), "nebula.staging")


def _old_dir() -> str:
    return os.path.join(shared_root(), "nebula.old")


def nebula_exe_path() -> str:
    return os.path.join(nebula_dir(), "nebula.exe")


def _asset_name() -> str:
    machine = (platform.machine() or "").lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    return f"nebula-windows-{arch}.zip"


def installed_version() -> "str | None":
    """`nebula -version` of the service-managed install, e.g. "1.11.2", or None."""
    import subprocess  # nosec B404 - fixed argv, our own verified binary

    exe = nebula_exe_path()
    if not os.path.isfile(exe):
        return None
    try:
        result = subprocess.run(  # nosec B603
            [exe, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"v?(\d+\.\d+\.\d+)", (result.stdout or "") + (result.stderr or ""))
    return match.group(1) if match else None


def latest_tag() -> str:
    import requests

    try:
        r = requests.get(_API_LATEST, headers={"User-Agent": _USER_AGENT}, timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        tag = r.json().get("tag_name") or ""
    except Exception as e:
        raise NebulaInstallError(f"Could not look up the latest Nebula release: {e}") from e
    if not _TAG_RE.match(tag):
        raise NebulaInstallError(f"Unexpected Nebula release tag {tag!r}")
    return tag


def _download(url: str, dest_path: str) -> None:
    import requests

    try:
        with requests.get(url, headers={"User-Agent": _USER_AGENT}, timeout=_HTTP_TIMEOUT, stream=True) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
    except Exception as e:
        raise NebulaInstallError(f"Download failed ({url}): {e}") from e


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_shasums(text: str) -> dict[str, str]:
    """SHASUM256.txt lines are "<hex>  <name>", where name is either the
    archive ("nebula-windows-amd64.zip") or a file inside it
    ("nebula-windows-amd64.zip/nebula.exe")."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def _safe_extract(zf: zipfile.ZipFile, dest: str) -> None:
    """Extract every entry, refusing absolute paths / drive letters / `..`
    escapes (zip-slip)."""
    dest_abs = os.path.abspath(dest)
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in name.split("/"):
            raise NebulaInstallError(f"Refusing unsafe path in archive: {info.filename!r}")
        target = os.path.abspath(os.path.join(dest_abs, name))
        if os.path.commonpath([dest_abs, target]) != dest_abs:
            raise NebulaInstallError(f"Refusing unsafe path in archive: {info.filename!r}")
    zf.extractall(dest_abs)


def prepare(tag: "str | None" = None) -> str:
    """Download, verify and extract a release into the staging dir. Returns
    the tag staged. Never touches the live install. Raises NebulaInstallError."""
    tag = tag or latest_tag()
    if not _TAG_RE.match(tag):
        raise NebulaInstallError(f"Invalid Nebula release tag {tag!r}")
    asset = _asset_name()

    staging = _staging_dir()
    shutil.rmtree(staging, ignore_errors=True)

    with tempfile.TemporaryDirectory(prefix="nc-nebula-", dir=shared_root()) as tmp:
        zip_path = os.path.join(tmp, asset)
        sums_path = os.path.join(tmp, "SHASUM256.txt")
        _download(_DOWNLOAD.format(tag=tag, name="SHASUM256.txt"), sums_path)
        _download(_DOWNLOAD.format(tag=tag, name=asset), zip_path)

        with open(sums_path, "r", encoding="utf-8", errors="replace") as f:
            sums = _parse_shasums(f.read())
        expected = sums.get(asset)
        if not expected:
            raise NebulaInstallError(f"{asset} has no entry in SHASUM256.txt for {tag} - refusing to install")
        actual = _sha256_file(zip_path)
        if actual != expected:
            raise NebulaInstallError(
                f"Checksum mismatch for {asset} ({tag}): expected {expected}, got {actual} - refusing to install"
            )

        os.makedirs(staging)
        try:
            with zipfile.ZipFile(zip_path) as zf:
                _safe_extract(zf, staging)
            for exe in ("nebula.exe", "nebula-cert.exe"):
                path = os.path.join(staging, exe)
                if not os.path.isfile(path):
                    raise NebulaInstallError(f"{exe} not found in {asset}")
                inner_expected = sums.get(f"{asset}/{exe}")
                if inner_expected and _sha256_file(path) != inner_expected:
                    raise NebulaInstallError(f"Checksum mismatch for {exe} inside {asset} - refusing to install")
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    return tag


def swap() -> None:
    """Make the staged install live. Caller must have stopped nebula.exe
    first (Windows can't replace a running executable)."""
    staging, live, old = _staging_dir(), nebula_dir(), _old_dir()
    if not os.path.isfile(os.path.join(staging, "nebula.exe")):
        raise NebulaInstallError("No staged Nebula install to activate")
    shutil.rmtree(old, ignore_errors=True)
    if os.path.exists(live):
        os.replace(live, old)
    try:
        os.replace(staging, live)
    except OSError:
        if os.path.exists(old) and not os.path.exists(live):
            os.replace(old, live)
        raise
    shutil.rmtree(old, ignore_errors=True)
