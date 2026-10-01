"""
The client's own version.

Release builds get it stamped in at build time: CI runs client/stamp_version.py, which
writes client/_build_version.py (git-ignored) from the release tag before PyInstaller
freezes the binaries, so the frozen ncclient / Windows service know which release they
are. Nix builds stamp only GIT_COMMIT / SOURCE_DATE (nix/client-package.nix), since a
flake has no release tag. Anything else - running from a checkout, a dev build -
reports DEV_VERSION, and client/updates.py never auto-updates a dev build.
"""
from __future__ import annotations

DEV_VERSION = "0.0.0+dev"

try:
    from client import _build_version as _stamp  # type: ignore[attr-defined]
except ImportError:  # not a stamped build
    _stamp = None

VERSION: str = getattr(_stamp, "VERSION", None) or DEV_VERSION
# Commit the build came from, and that commit's time (Unix seconds); None if unknown.
GIT_COMMIT: str | None = getattr(_stamp, "GIT_COMMIT", None)
SOURCE_DATE: int | None = getattr(_stamp, "SOURCE_DATE", None)
# Only ever set by a local test build (stamp_version.py --test-key/--test-manifest-url),
# never by CI: an extra trusted update-signing key and a different manifest URL.
UPDATE_TEST_KEY: str | None = getattr(_stamp, "UPDATE_TEST_KEY", None)
UPDATE_TEST_MANIFEST_URL: str | None = getattr(_stamp, "UPDATE_TEST_MANIFEST_URL", None)


def is_dev_build(version: str = VERSION) -> bool:
    return "+dev" in version or version == DEV_VERSION
