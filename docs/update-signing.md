# Update manifest signing key

Automatic client updates (`client/updates.py`) only trust
`https://pkgs.nebulacommander.com/updates/latest.json` when its detached signature
(`latest.json.sig`) verifies against one of the Ed25519 public keys built into the
client (`client/update_keys.py`). CI signs the manifest in
`.github/workflows/publish-package-repo.yml` with the `UPDATE_SIGNING_KEY` secret.

## One-time setup

1. Generate a key pair on a trusted machine:

   ```sh
   python3 packaging/repo/build_update_manifest.py --generate-key > update-key.txt
   ```

2. Store the private key (the `-----BEGIN PRIVATE KEY-----` block) as a secret:

   ```sh
   sed -n '/BEGIN/,/END/p' update-key.txt | gh secret set UPDATE_SIGNING_KEY
   ```

3. Add the public key (the last line) to `PUBLIC_KEYS` in `client/update_keys.py` and
   commit it. Releases built from then on trust it.

4. Delete `update-key.txt` (keep an offline backup of the private key if you want one;
   losing it only means rotating, below).

Until the secret is set, the package repo still publishes, without a manifest, and
clients report "Could not fetch" for update checks.

## Rotating

Add the new public key to `PUBLIC_KEYS` next to the old one and release. Once clients
have that release, switch the secret to the new private key, and remove the old public
key in a later release. If the private key leaks, remove its public key and release
immediately: clients that haven't updated yet still trust it until they do.

## What a signature does and doesn't cover

The manifest names the version, release tag, commit, and each installer's URL and
SHA-256. The client refuses a manifest with a bad signature, a version that isn't
newer, or an installer URL outside
`https://github.com/NixRTR/nebula-commander/releases/download/`, and refuses an
installer whose SHA-256 doesn't match. The Windows MSI itself isn't code-signed yet.
