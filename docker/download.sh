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

echo "Done. Next steps:"
echo "  1. cp .env.example .env"
echo "  2. cp -r env.d.example env.d"
echo "  3. Edit env.d/backend (set JWT secret, OIDC, etc.)"
echo "  4. docker network create nebula-commander   # if not already created"
echo "  5. docker compose pull && docker compose up -d"
echo "  (With Keycloak: docker compose -f docker-compose.yml -f docker-compose-keycloak.yml up -d)"
