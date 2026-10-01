#!/usr/bin/env python3
"""
Build and sign the client auto-update manifest (client/updates.py), served next to
the package repo at https://pkgs.nebulacommander.com/updates/latest.json(.sig).

  # CI (publish-package-repo.yml), signing key in $UPDATE_SIGNING_KEY (PEM):
  python3 packaging/repo/build_update_manifest.py --tag v0.7.0 \\
      --sums SHA256SUMS.txt --released 2026-10-01T12:00:00Z --output site/updates

  # One-time: make a signing key pair (see docs/update-signing.md):
  python3 packaging/repo/build_update_manifest.py --generate-key

The signature is base64 of a raw Ed25519 signature over latest.json's exact bytes.
Before writing anything, the result is verified against the public keys the client
ships with (client/update_keys.py), so a key mismatch fails the build here instead
of every client refusing the manifest later.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess  # nosec B404 - fixed git argv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASES = "https://github.com/NixRTR/nebula-commander/releases/download"
# manifest asset key -> release asset name
ASSETS = {"windows-amd64": "NebulaCommander-windows-amd64.msi"}


def parse_sums(text: str) -> "dict[str, str]":
    sums = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            sums[parts[1].lstrip("*")] = parts[0].lower()
    return sums


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout.strip()  # nosec B603 B607


def build_manifest(tag: str, sums: "dict[str, str]", released: str, git_commit: str, commit_time: int) -> dict:
    version = tag[1:] if tag.startswith("v") else tag
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit(f"{tag} is not a stable release tag")
    assets = {}
    for key, name in ASSETS.items():
        if name in sums:
            assets[key] = {"url": f"{RELEASES}/{tag}/{name}", "sha256": sums[name]}
        else:
            print(f"warning: {name} not in SHA256SUMS - no {key} update in this manifest", file=sys.stderr)
    return {
        "schema": 1,
        "version": version,
        "tag": tag,
        "git_commit": git_commit,
        "commit_time": commit_time,
        "released": released,
        "assets": assets,
    }


def sign(body: bytes, private_pem: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    key = load_pem_private_key(private_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise SystemExit("UPDATE_SIGNING_KEY is not an Ed25519 private key")
    return base64.b64encode(key.sign(body))


def verify_with_client_keys(body: bytes, sig: bytes) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from client.update_keys import PUBLIC_KEYS
    from client.updates import UpdateError, verify_manifest

    try:
        verify_manifest(body, sig, [base64.b64decode(k) for k in PUBLIC_KEYS])
    except UpdateError as e:
        raise SystemExit(f"The signed manifest doesn't verify with client/update_keys.py: {e}")


def generate_key() -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )

    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    pub = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    print("# Private key: store as the UPDATE_SIGNING_KEY repository secret, then delete this output.")
    print(pem)
    print("# Public key: add to PUBLIC_KEYS in client/update_keys.py")
    print(pub)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--generate-key", action="store_true")
    ap.add_argument("--tag")
    ap.add_argument("--sums", help="the release's SHA256SUMS.txt")
    ap.add_argument("--released", help="the release's publish time (ISO 8601)")
    ap.add_argument("--output", help="directory for latest.json and latest.json.sig")
    args = ap.parse_args()
    if args.generate_key:
        generate_key()
        return 0
    if not (args.tag and args.sums and args.released and args.output):
        ap.error("--tag, --sums, --released and --output are required")

    private_pem = os.environ.get("UPDATE_SIGNING_KEY", "").encode()
    if not private_pem.strip():
        raise SystemExit("UPDATE_SIGNING_KEY is not set")
    commit = _git("rev-list", "-n", "1", args.tag)
    commit_time = int(_git("log", "-1", "--format=%ct", commit))
    manifest = build_manifest(args.tag, parse_sums(Path(args.sums).read_text()), args.released, commit, commit_time)
    body = (json.dumps(manifest, indent=2) + "\n").encode()
    sig = sign(body, private_pem)
    verify_with_client_keys(body, sig)

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "latest.json").write_bytes(body)
    (out / "latest.json.sig").write_bytes(sig + b"\n")
    print(f"Signed update manifest for {args.tag} ({', '.join(manifest['assets']) or 'no assets'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
