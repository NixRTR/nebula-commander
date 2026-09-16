"""Update-check API: compares the running version against the latest GitHub release."""
import logging
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter

from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["version"])

# Set from the release tag via the VERSION build-arg (see docker/backend/Dockerfile);
# "dev" outside that build. Mirrors the same env var main.py reads.
VERSION = os.getenv("VERSION", "dev")

GITHUB_RELEASES_URL = "https://api.github.com/repos/NixRTR/nebula-commander/releases/latest"

_CACHE_TTL_SUCCESS = 3600  # 1 hour
_CACHE_TTL_FAILURE = 900  # 15 minutes - retry sooner, but still avoid hammering an
                           # unreachable network (e.g. air-gapped deployment) on every page load

_cache: dict = {"checked_at": 0.0, "latest_version": None, "release_url": None}


def _parse_semver(v: str) -> Optional[tuple[int, int, int]]:
    """Parse a leading 'X.Y.Z' from a version string (tolerating a 'v' prefix and a
    trailing pre-release suffix like '-rc1'). Returns None if it doesn't look like one -
    e.g. "dev", "latest", or anything else that isn't a real release version."""
    parts = v.lstrip("vV").split(".")
    if len(parts) < 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2].split("-")[0]))
    except ValueError:
        return None


async def _fetch_latest_release() -> None:
    """Refresh the cached latest-release info from GitHub. Never raises - a failed or
    unreachable check just leaves the previous cached value (or None) in place."""
    now = time.time()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                GITHUB_RELEASES_URL,
                headers={"Accept": "application/vnd.github+json", "User-Agent": "nebula-commander"},
            )
            resp.raise_for_status()
            data = resp.json()
        _cache["latest_version"] = (data.get("tag_name") or "").lstrip("vV") or None
        _cache["release_url"] = data.get("html_url")
        _cache["checked_at"] = now
    except Exception as e:
        logger.debug("Update check failed (will retry later): %s", e)
        # Schedule a sooner retry than a successful check would, without a separate timer.
        _cache["checked_at"] = now - (_CACHE_TTL_SUCCESS - _CACHE_TTL_FAILURE)


@router.get("/api/version-check")
async def version_check() -> dict:
    """
    Compare the running version against the latest GitHub release (no auth required).
    Cached in-memory (1 hour on success, 15 minutes on failure) so this never adds a
    GitHub API call to every page load. Disabled entirely - no outbound request ever
    made - when NEBULA_COMMANDER_UPDATE_CHECK_ENABLED=false.
    """
    if not settings.update_check_enabled:
        return {
            "current_version": VERSION,
            "latest_version": None,
            "release_url": None,
            "update_available": False,
            "check_enabled": False,
        }

    if time.time() - _cache["checked_at"] > _CACHE_TTL_SUCCESS:
        await _fetch_latest_release()

    current = _parse_semver(VERSION)
    latest = _parse_semver(_cache["latest_version"] or "")
    update_available = bool(current and latest and latest > current)

    return {
        "current_version": VERSION,
        "latest_version": _cache["latest_version"],
        "release_url": _cache["release_url"],
        "update_available": update_available,
        "check_enabled": True,
    }
