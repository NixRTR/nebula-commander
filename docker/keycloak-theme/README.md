# Keycloak theme with Nebula background and logo

This theme makes Keycloak’s **login** and **logout** (account) pages match the app login screen: same nebula background image, overlay, logo, and “Nebula Commander” branding. Styling is **Flowbite-inspired** (rounded inputs, purple primary button, dark card).

## Zero-touch (recommended)

When using **realm import** (see [keycloak-import/README.md](keycloak-import/README.md)), the **nebula-commander** realm is created at startup with **Login theme** and **Account theme** already set to **nebula**. No manual steps are required.

- **Background**: Same as frontend — `nebula/login/resources/img/nebula-bg.webp` (copy from `frontend/public/nebula-bg.webp` if you add it there). A dark overlay is applied in CSS to match the frontend.
- **Header**: Logo (`logo.svg`) and “Nebula Commander” in large text, plus subtitle “Sign in to manage your Nebula network”.
- The theme is mounted in `docker-compose-keycloak.yml`. Start Keycloak with the Keycloak compose file; the imported realm will use this theme automatically.

## Manual setup (if not using realm import)

If you use a different realm or create the realm manually:

1. **Theme assets**: `nebula-bg.webp` and `logo.svg` in `nebula/login/resources/img/`. Use the same `nebula-bg.webp` as in `frontend/public` for identical background.
2. In Keycloak Admin: **Realm settings** → **Themes** → set **Login theme** and **Account theme** to **nebula** → **Save**.

## Structure

- `nebula/login/theme.properties` – extends Keycloak 26 theme (`keycloak.v2`).
- `nebula/login/login.ftl` – overrides the login header (logo + “Nebula Commander” + subtitle).
- `nebula/login/resources/css/login.css` – background, overlay, card, form and button styling (Flowbite-like).
- `nebula/login/resources/img/nebula-bg.webp` – background (same as frontend).
- `nebula/login/resources/img/logo.svg` – logo.

## Flowbite

The theme uses **Flowbite-inspired** CSS (rounded inputs, purple primary, dark card). To use the full Flowbite library (e.g. for dropdowns or modals), you would need to override `template.ftl` and add Flowbite’s CDN link in the `<head>`; the current setup avoids that to keep the theme simple and stable across Keycloak upgrades.
