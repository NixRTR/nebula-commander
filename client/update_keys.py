"""
Public keys trusted to sign the auto-update manifest (client/updates.py).

Base64 of raw 32-byte Ed25519 public keys. The matching private key is the
UPDATE_SIGNING_KEY secret that .github/workflows/publish-package-repo.yml signs
updates/latest.json with (see docs/update-signing.md). A list, so a new key can be
added a release before the old one is retired.
"""

PUBLIC_KEYS: "list[str]" = [
]
