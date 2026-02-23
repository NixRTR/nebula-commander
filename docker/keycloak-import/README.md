# Keycloak realm import (zero-touch)

The file `nebula-commander-realm.json` is imported by Keycloak at startup when using `start-dev --import-realm`. The realm is only created if it does not already exist.

## Required environment variables (for placeholders)

These must be available to the **Keycloak container** (e.g. via `env.d/keycloak/keycloak` or by passing `env.d/backend` as an extra env file):

| Variable | Description |
|----------|-------------|
| `NEBULA_COMMANDER_PUBLIC_URL` | **Required.** Public app URL (FQDN or host:port). Substituted into the realm JSON at startup for redirect URI, web origins, and post-logout redirects. Redirect URI becomes `PUBLIC_URL` + `/api/auth/callback`. |
| `NEBULA_COMMANDER_OIDC_CLIENT_SECRET` | Client secret for the nebula-commander client. Must match the backend config. |

The Keycloak container runs a startup step that substitutes these variables in the realm JSON (Keycloak does not do this itself). Set them in `env.d/backend`; the Docker Compose Keycloak stack includes that file.

**If login fails with "Invalid scopes: openid profile email"**: the imported client only has the custom scope by default. In Keycloak Admin → Clients → nebula-commander → Client scopes, add **openid** (and optionally **profile**, **email**) to "Assigned default client scopes".

## Backend configuration

When using this imported realm, set the backend OIDC issuer to the nebula-commander realm:

```bash
NEBULA_COMMANDER_OIDC_ISSUER_URL=http://keycloak:8080/realms/nebula-commander
```

(Use the host and port that match your setup; replace `keycloak` with your Keycloak host if different.)
