# Keycloak realm import (zero-touch)

The file `nebula-commander-realm.json` is imported by Keycloak at startup when using `start-dev --import-realm`. The realm is only created if it does not already exist.

When using the **custom Keycloak image** (see docker/README.md), this realm JSON is baked into the image. At container startup, the image’s startup script substitutes the placeholders using environment variables, then Keycloak runs with `--import-realm`. No host mount is required.

## Required environment variables (for placeholders)

These must be available to the **Keycloak container** (e.g. via `env.d/keycloak/keycloak` or by passing `env.d/backend` as an extra env file):

| Variable | Description |
|----------|-------------|
| `NEBULA_COMMANDER_PUBLIC_URL` | **Required.** Must be the **backend** base URL (scheme + host + port where `/api/auth/*` is served). Substituted into the realm JSON for Valid Redirect URIs and web origins. Example: if the backend is at `http://192.168.3.200:9090`, set this to `http://192.168.3.200:9090`. It must match the backend’s `NEBULA_COMMANDER_OIDC_REDIRECT_URI` (or derived `public_url`) base, or Keycloak will reject redirects with `invalid_redirect_uri`. |
| `NEBULA_COMMANDER_OIDC_CLIENT_SECRET` | Client secret for the nebula-commander client. Must match the backend config. |

The Keycloak container runs a startup step that substitutes these variables in the realm JSON (Keycloak does not do this itself). Set them in `env.d/backend`; the Docker Compose Keycloak stack includes that file.

**If login or reauth fails with "Invalid parameter: redirect_url" / "invalid_redirect_uri"**: Keycloak’s Valid Redirect URIs do not match what the backend sends. Ensure `NEBULA_COMMANDER_PUBLIC_URL` in the **Keycloak** env is exactly the backend base URL (e.g. `http://192.168.3.200:9090`). If the realm was already imported with a different URL, either: (1) in Keycloak Admin → Clients → nebula-commander → Valid redirect URIs, add `{BACKEND_BASE}/api/auth/callback` and `{BACKEND_BASE}/api/auth/reauth/callback` (with your backend base URL), or (2) set the correct `NEBULA_COMMANDER_PUBLIC_URL`, remove the realm (or delete the client), restart Keycloak so the realm is re-imported with the new URLs.

**If login fails with "Invalid scopes: openid profile email"**: the imported client only has the custom scope by default. In Keycloak Admin → Clients → nebula-commander → Client scopes, add **openid** (and optionally **profile**, **email**) to "Assigned default client scopes".

## Backend configuration

When using this imported realm, set the backend OIDC issuer to the nebula-commander realm:

```bash
NEBULA_COMMANDER_OIDC_ISSUER_URL=http://keycloak:8080/realms/nebula-commander
```

(Use the host and port that match your setup; replace `keycloak` with your Keycloak host if different.)
