#!/usr/bin/env python3
"""
Stamp the release version into the client before it's frozen (see client/version.py).

  python client/stamp_version.py            # from $NC_VERSION, else a v* $GITHUB_REF_NAME
  python client/stamp_version.py 0.7.0      # explicit

Writes client/_build_version.py. Does nothing (and removes a stale stamp) when no
release version is available, so non-tag CI runs and local builds stay dev builds.

For testing auto-update locally only (never in CI):
  --test-key <base64 Ed25519 public key>   trust this extra manifest signing key
  --test-manifest-url <url>                fetch the manifest from here instead
  --test-asset-prefix <url>                also allow installers under this URL
"""
import argparse
import os
import re
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "_build_version.py"


def release_version(arg: "str | None") -> "str | None":
    raw = arg or os.environ.get("NC_VERSION", "")
    if not raw:
        ref = os.environ.get("GITHUB_REF_NAME", "")
        raw = ref if ref.startswith("v") else ""
    raw = raw.strip().lstrip("v")
    return raw if re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", raw) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("version", nargs="?")
    ap.add_argument("--test-key")
    ap.add_argument("--test-manifest-url")
    ap.add_argument("--test-asset-prefix")
    args = ap.parse_args()
    version = release_version(args.version)
    if version is None:
        TARGET.unlink(missing_ok=True)
        print("stamp_version: no release version; leaving a dev build")
        return 0
    lines = [f"VERSION = {version!r}"]
    sha = os.environ.get("GITHUB_SHA", "")
    if re.fullmatch(r"[0-9a-f]{40}", sha):
        lines.append(f"GIT_COMMIT = {sha!r}")
    if args.test_key:
        lines.append(f"UPDATE_TEST_KEY = {args.test_key!r}")
    if args.test_manifest_url:
        lines.append(f"UPDATE_TEST_MANIFEST_URL = {args.test_manifest_url!r}")
    if args.test_asset_prefix:
        lines.append(f"UPDATE_TEST_ASSET_PREFIX = {args.test_asset_prefix!r}")
    TARGET.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"stamp_version: client version {version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
