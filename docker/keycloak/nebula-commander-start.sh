#!/bin/sh
set -e

# Substitute env vars in the realm JSON (Keycloak does not do this itself).
# Source is a read-only bind mount; write the rendered file into Keycloak's
# own (unmounted, container-internal) import directory rather than back into
# the mount, so the host's checkout is never modified.
SRC=/keycloak-import-src/nebula-commander-realm.json
DEST=/opt/keycloak/data/import/nebula-commander-realm.json

mkdir -p /opt/keycloak/data/import

if [ -f "$SRC" ]; then
  sed -e "s|\${NEBULA_COMMANDER_PUBLIC_URL}|${NEBULA_COMMANDER_PUBLIC_URL}|g" \
      -e "s|\${NEBULA_COMMANDER_OIDC_CLIENT_SECRET}|${NEBULA_COMMANDER_OIDC_CLIENT_SECRET}|g" \
      "$SRC" > "$DEST"
fi

exec /opt/keycloak/bin/kc.sh start-dev --import-realm
