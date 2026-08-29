"""
Shared logic for downloading and version-checking the Nebula binary release from GitHub.
Used by the Windows tray app (runtime auto-update check) and windows/build.py (bundling
a pinned Nebula version at build time) - previously duplicated separately in each.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess  # nosec B404 - used with shell=False and validated/fixed args
import tempfile
import zipfile
from typing import Callable, Optional

NEBULA_VERSION_DEFAULT = "v1.10.2"
NEBULA_URL_TEMPLATE = "https://github.com/slackhq/nebula/releases/download/{version}/nebula-windows-amd64.zip"
NEBULA_RELEASES_URL = "https://github.com/slackhq/nebula/releases"
NEBULA_API_LATEST = "https://api.github.com/repos/slackhq/nebula/releases/latest"


def _validate_github_url(url: str) -> None:
    """Reject anything that isn't a fixed, trusted GitHub host - defense in depth
    for the urlretrieve/urlopen calls below, even though callers never pass a
    non-GitHub URL today."""
    if not (url.startswith("https://github.com/") or url.startswith("https://api.github.com/")):
        raise ValueError(f"Refusing to fetch non-GitHub URL: {url}")


def _noop_log(_msg: str) -> None:
    pass


def download_nebula_to_dir(
    version: str,
    dest_dir: str,
    log: Callable[[str], None] = _noop_log,
) -> tuple[bool, Optional[str], str]:
    """
    Download the Nebula Windows release zip and extract nebula.exe into dest_dir.
    Returns (success, path_to_exe or None, error_message).
    """
    import traceback
    import urllib.request

    url = NEBULA_URL_TEMPLATE.format(version=version)
    _validate_github_url(url)
    exe_path = os.path.join(dest_dir, "nebula.exe")
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(tempfile.gettempdir(), "nebula-windows-amd64.zip")
    log(f"Download Nebula: version={version}, url={url}, dest_dir={dest_dir}")
    try:
        log("Download Nebula: requesting URL...")
        urllib.request.urlretrieve(url, zip_path)  # nosec B310 - fixed https:// GitHub host, scheme validated above
        log(f"Download Nebula: saved to {zip_path}, size={os.path.getsize(zip_path)}")
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        log(f"Download Nebula failed: {err_msg}")
        log(traceback.format_exc())
        return False, None, err_msg
    try:
        log("Download Nebula: opening zip...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            log(f"Download Nebula: archive entries: {names}")
            for name in names:
                if name.endswith("nebula.exe"):
                    with zf.open(name) as src:
                        with open(exe_path, "wb") as dst:
                            dst.write(src.read())
                    log(f"Download Nebula: extracted to {exe_path}")
                    return True, exe_path, ""
            log("Download Nebula: nebula.exe not found in archive")
            return False, None, "nebula.exe not found in archive"
    except Exception as e:
        err_msg = f"{type(e).__name__}: {e}"
        log(f"Download Nebula extract failed: {err_msg}")
        log(traceback.format_exc())
        return False, None, err_msg
    finally:
        try:
            os.remove(zip_path)
            log("Download Nebula: removed temp zip")
        except OSError as e:
            log(f"Download Nebula: could not remove temp zip: {e}")


def get_nebula_version(nebula_bin: str, log: Callable[[str], None] = _noop_log) -> Optional[str]:
    """Run nebula -version (or --version) and parse version string. Returns e.g. '1.10.2' or None."""
    for flag in ("-version", "--version"):
        try:
            out = subprocess.run(  # nosec B603 - resolved via shutil.which, shell=False
                [shutil.which(nebula_bin) or nebula_bin, flag],
                capture_output=True,
                text=True,
                timeout=10,
            )
            text = (out.stdout or "") + (out.stderr or "")
            m = re.search(r"v?(\d+\.\d+\.\d+)", text)
            if m:
                return m.group(1)
        except Exception as e:
            log(f"nebula {flag} failed: {e}")
    return None


def fetch_latest_nebula_tag(log: Callable[[str], None] = _noop_log) -> Optional[str]:
    """Fetch latest release tag from GitHub API. Returns e.g. 'v1.10.3' or None."""
    import urllib.request

    try:
        _validate_github_url(NEBULA_API_LATEST)
        req = urllib.request.Request(
            NEBULA_API_LATEST,
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 - fixed https:// GitHub host, scheme validated above
            data = json.loads(resp.read().decode())
        tag = data.get("tag_name")
        return tag if isinstance(tag, str) and tag else None
    except Exception as e:
        log(f"Fetch latest Nebula tag failed: {e}")
        return None


def parse_version_tuple(version_str: str) -> tuple[int, int, int]:
    """Parse 'v1.10.2' or '1.10.2' to (1, 10, 2). Missing parts become 0."""
    m = re.search(r"v?(\d+)\.?(\d*)\.?(\d*)", (version_str or "").strip())
    if not m:
        return (0, 0, 0)
    a, b, c = m.group(1), m.group(2) or "0", m.group(3) or "0"
    return (int(a), int(b), int(c))


def is_newer_version(local_version: str, latest_tag: str) -> bool:
    """True if latest_tag is newer than local_version (e.g. '1.10.2' vs 'v1.10.3')."""
    return parse_version_tuple(latest_tag) > parse_version_tuple(local_version)
