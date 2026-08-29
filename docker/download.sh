#!/usr/bin/env bash
# Download Nebula Commander Docker files into the current directory.
# Does not install any software; only checks that Docker and Docker Compose are available.
set -e

BASE_URL="https://raw.githubusercontent.com/NixRTR/nebula-commander/main/docker"

echo "Checking prerequisites..."
MISSING=""
if ! command -v docker &>/dev/null; then
  MISSING="${MISSING}- docker (Docker Engine)\n"
fi
if ! docker compose version &>/dev/null 2>&1; then
  if ! command -v docker-compose &>/dev/null; then
    MISSING="${MISSING}- docker compose (or docker-compose)\n"
  fi
fi
if [ -n "$MISSING" ]; then
  echo "The following prerequisites are missing. Please install them before running Docker Compose."
  echo ""
  printf "$MISSING"
  echo "This script does not install software. Install Docker and Docker Compose, then run this script again."
  exit 1
fi
echo "Prerequisites OK."
echo ""

echo "Downloading Docker Compose and environment files..."
curl -sSL -o docker-compose.yml "${BASE_URL}/docker-compose.yml"
curl -sSL -o docker-compose-keycloak.yml "${BASE_URL}/docker-compose-keycloak.yml"
curl -sSL -o .env.example "${BASE_URL}/.env.example"
mkdir -p env.d.example/keycloak
curl -sSL -o env.d.example/backend "${BASE_URL}/env.d.example/backend"
curl -sSL -o env.d.example/keycloak/keycloak "${BASE_URL}/env.d.example/keycloak/keycloak"
curl -sSL -o env.d.example/keycloak/postgresql "${BASE_URL}/env.d.example/keycloak/postgresql"

mkdir -p keycloak keycloak-import keycloak-theme/nebula/login/resources/css \
         keycloak-theme/nebula/login/resources/img keycloak-theme/nebula/login/resources/js
# Keycloak login theme - keep this file list in sync with docker/keycloak-theme/
curl -sSL -o keycloak/nebula-commander-start.sh "${BASE_URL}/keycloak/nebula-commander-start.sh"
curl -sSL -o keycloak-import/README.md "${BASE_URL}/keycloak-import/README.md"
curl -sSL -o keycloak-import/nebula-commander-realm.json "${BASE_URL}/keycloak-import/nebula-commander-realm.json"
curl -sSL -o keycloak-theme/README.md "${BASE_URL}/keycloak-theme/README.md"
curl -sSL -o keycloak-theme/nebula/login/theme.properties "${BASE_URL}/keycloak-theme/nebula/login/theme.properties"
curl -sSL -o keycloak-theme/nebula/login/login.ftl "${BASE_URL}/keycloak-theme/nebula/login/login.ftl"
curl -sSL -o keycloak-theme/nebula/login/buttons.ftl "${BASE_URL}/keycloak-theme/nebula/login/buttons.ftl"
curl -sSL -o keycloak-theme/nebula/login/resources/logo.svg "${BASE_URL}/keycloak-theme/nebula/login/resources/logo.svg"
curl -sSL -o keycloak-theme/nebula/login/resources/css/login.css "${BASE_URL}/keycloak-theme/nebula/login/resources/css/login.css"
curl -sSL -o keycloak-theme/nebula/login/resources/js/ensure-login-submit.js "${BASE_URL}/keycloak-theme/nebula/login/resources/js/ensure-login-submit.js"
curl -sSL -o keycloak-theme/nebula/login/resources/img/logo.svg "${BASE_URL}/keycloak-theme/nebula/login/resources/img/logo.svg"
curl -sSL -o keycloak-theme/nebula/login/resources/img/nebula-bg.webp "${BASE_URL}/keycloak-theme/nebula/login/resources/img/nebula-bg.webp"
curl -sSL -o keycloak-theme/nebula/login/resources/img/nebula.webp "${BASE_URL}/keycloak-theme/nebula/login/resources/img/nebula.webp"

echo "Done. Next steps:"
echo "  1. cp .env.example .env"
echo "  2. cp -r env.d.example env.d"
echo "  3. Edit env.d/backend (set JWT secret, OIDC, etc.)"
echo "  4. docker network create nebula-commander   # if not already created"
echo "  5. docker compose pull && docker compose up -d"
echo "  (With Keycloak: docker compose -f docker-compose.yml -f docker-compose-keycloak.yml up -d)"
