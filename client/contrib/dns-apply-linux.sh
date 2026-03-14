#!/usr/bin/env bash
# Apply or remove split-horizon DNS from dns-client.json using systemd-resolved.
# Run as root. Usage: dns-apply-linux.sh [path-to-dns-client.json]
# Default path: /etc/nebula/dns-client.json (or $NEBULA_OUTPUT_DIR/dns-client.json if set).

set -eu

OUTPUT_DIR="${NEBULA_OUTPUT_DIR:-/etc/nebula}"
CONF_PATH="${1:-${OUTPUT_DIR}/dns-client.json}"
DROPIN="/etc/systemd/resolved.conf.d/nebula-dns.conf"

if [ ! -f "${CONF_PATH}" ]; then
  # No config: remove drop-in and restart
  rm -f "${DROPIN}"
  systemctl restart systemd-resolved 2>/dev/null || true
  exit 0
fi

domain=""
servers=""
# Parse domain and dns_servers from JSON (minimal: one line or jq if available)
if command -v jq >/dev/null 2>&1; then
  domain="$(jq -r '.domain // empty' "${CONF_PATH}")"
  servers="$(jq -r '(.dns_servers // []) | join(" ")' "${CONF_PATH}")"
else
  # Fallback: grep/sed for "domain" and "dns_servers"
  domain="$(grep -o '"domain"[[:space:]]*:[[:space:]]*"[^"]*"' "${CONF_PATH}" | sed 's/.*"\([^"]*\)"[[:space:]]*$/\1/' | head -1)"
  servers="$(grep -o '"dns_servers"[[:space:]]*:[[:space:]]*\[[^]]*\]' "${CONF_PATH}" | sed 's/.*\[\([^]]*\)\].*/\1/' | tr ',' ' ' | tr -d '"' | xargs)"
fi

if [ -z "${domain}" ] || [ -z "${servers}" ]; then
  rm -f "${DROPIN}"
  systemctl restart systemd-resolved 2>/dev/null || true
  exit 0
fi

mkdir -p "$(dirname "${DROPIN}")"
cat > "${DROPIN}" << EOF
[Resolve]
Domains=~${domain}
DNS=${servers}
EOF
systemctl restart systemd-resolved
