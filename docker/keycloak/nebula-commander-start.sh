#!/bin/sh
set -e

# Substitute env vars in realm JSON (Keycloak does not do this)
if [ -f /opt/keycloak/data/import/nebula-commander-realm.json ]; then
  sed -e "s|\${NEBULA_COMMANDER_PUBLIC_URL}|${NEBULA_COMMANDER_PUBLIC_URL}|g" \
      -e "s|\${NEBULA_COMMANDER_OIDC_CLIENT_SECRET}|${NEBULA_COMMANDER_OIDC_CLIENT_SECRET}|g" \
      /opt/keycloak/data/import/nebula-commander-realm.json > /tmp/realm.json
  mv /tmp/realm.json /opt/keycloak/data/import/nebula-commander-realm.json
fi

exec /opt/keycloak/bin/kc.sh start-dev --import-realm
