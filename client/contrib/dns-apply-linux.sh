#!/usr/bin/env bash
# Apply or remove split-horizon DNS from dns-client.json.
# Tries backends in order: systemd-resolved, dnsmasq, /etc/resolv.conf (last is best-effort, not true split-horizon).
# Run as root. Usage: dns-apply-linux.sh [path-to-dns-client.json]
# Default path: /etc/nebula/dns-client.json (or $NEBULA_OUTPUT_DIR/dns-client.json if set).

set -eu

OUTPUT_DIR="${NEBULA_OUTPUT_DIR:-/etc/nebula}"
CONF_PATH="${1:-${OUTPUT_DIR}/dns-client.json}"
DROPIN="/etc/systemd/resolved.conf.d/nebula-dns.conf"
DNSMASQ_CONF="/etc/dnsmasq.d/nebula-commander.conf"
RESOLV_CONF="/etc/resolv.conf"
RESOLV_BACKUP="/etc/resolv.conf.nebula-commander.bak"
RESOLV_MARKER="# nebula-commander"

apply_resolved() {
  local domain="$1"
  local servers="$2"
  mkdir -p "$(dirname "${DROPIN}")"
  cat > "${DROPIN}" << EOF
[Resolve]
Domains=~${domain}
DNS=${servers}
EOF
  systemctl restart systemd-resolved 2>/dev/null || true
}

remove_resolved() {
  rm -f "${DROPIN}"
  systemctl restart systemd-resolved 2>/dev/null || true
}

apply_dnsmasq() {
  local domain="$1"
  shift
  local servers=("$@")
  mkdir -p "$(dirname "${DNSMASQ_CONF}")"
  echo "# Split-horizon for Nebula Commander domain ${domain}" > "${DNSMASQ_CONF}"
  for ip in "${servers[@]}"; do
    echo "server=/.${domain}/${ip}" >> "${DNSMASQ_CONF}"
  done
  systemctl restart dnsmasq 2>/dev/null || service dnsmasq restart 2>/dev/null || true
}

remove_dnsmasq() {
  rm -f "${DNSMASQ_CONF}"
  systemctl restart dnsmasq 2>/dev/null || service dnsmasq restart 2>/dev/null || true
}

apply_resolv_conf() {
  local domain="$1"
  shift
  local servers=("$@")
  cp -f "${RESOLV_CONF}" "${RESOLV_BACKUP}" 2>/dev/null || true
  {
    cat "${RESOLV_CONF}" 2>/dev/null || true
    echo ""
    echo "${RESOLV_MARKER}"
    echo "search ${domain}"
    for ip in "${servers[@]}"; do
      echo "nameserver ${ip}"
    done
  } > "${RESOLV_CONF}.tmp"
  mv -f "${RESOLV_CONF}.tmp" "${RESOLV_CONF}"
}

remove_resolv_conf() {
  if [ -f "${RESOLV_BACKUP}" ]; then
    cp -f "${RESOLV_BACKUP}" "${RESOLV_CONF}"
    rm -f "${RESOLV_BACKUP}"
  elif [ -f "${RESOLV_CONF}" ]; then
    awk -v m="${RESOLV_MARKER}" '
      index($0, m) { skip=1; next }
      skip && ($0 ~ /^[[:space:]]*nameserver / || $0 ~ /^[[:space:]]*search /) { next }
      { skip=0; print }
    ' "${RESOLV_CONF}" > "${RESOLV_CONF}.tmp" 2>/dev/null && mv -f "${RESOLV_CONF}.tmp" "${RESOLV_CONF}" || true
  fi
}

# Remove from all backends (idempotent)
remove_all() {
  remove_resolved
  remove_dnsmasq
  remove_resolv_conf
}

if [ ! -f "${CONF_PATH}" ]; then
  remove_all
  exit 0
fi

domain=""
servers=""
if command -v jq >/dev/null 2>&1; then
  domain="$(jq -r '.domain // empty' "${CONF_PATH}")"
  servers="$(jq -r '(.dns_servers // []) | join(" ")' "${CONF_PATH}")"
else
  domain="$(grep -o '"domain"[[:space:]]*:[[:space:]]*"[^"]*"' "${CONF_PATH}" | sed 's/.*"\([^"]*\)"[[:space:]]*$/\1/' | head -1)"
  servers="$(grep -o '"dns_servers"[[:space:]]*:[[:space:]]*\[[^]]*\]' "${CONF_PATH}" | sed 's/.*\[\([^]]*\)\].*/\1/' | tr ',' ' ' | tr -d '"' | xargs)"
fi

if [ -z "${domain}" ] || [ -z "${servers}" ]; then
  remove_all
  exit 0
fi

# Build servers array for resolv/dnsmasq
servers_arr=()
for s in ${servers}; do
  servers_arr+=( "$s" )
done

# 1. Try systemd-resolved
apply_resolved "${domain}" "${servers}"
if systemctl is-active systemd-resolved >/dev/null 2>&1; then
  echo "Split-horizon DNS applied via systemd-resolved."
  exit 0
fi

# 2. Try dnsmasq (snippet works when dnsmasq is the system resolver or used locally)
if [ -d /etc/dnsmasq.d ] && command -v dnsmasq >/dev/null 2>&1; then
  remove_resolved
  apply_dnsmasq "${domain}" "${servers_arr[@]}"
  if systemctl is-active dnsmasq >/dev/null 2>&1; then
    echo "Split-horizon DNS applied via dnsmasq."
    exit 0
  fi
  remove_dnsmasq
fi

# 3. Fallback: /etc/resolv.conf (not true split-horizon; best-effort)
if [ -e "${RESOLV_CONF}" ]; then
  real="$(readlink -f "${RESOLV_CONF}" 2>/dev/null || true)"
  if [ -z "${real}" ] || { [ -n "${real}" ] && [[ "${real}" != *"/systemd/resolve/"* ]] && [[ "${real}" != *"/NetworkManager/"* ]]; }; then
    remove_resolved
    remove_dnsmasq
    apply_resolv_conf "${domain}" "${servers_arr[@]}"
    echo "Split-horizon DNS applied via /etc/resolv.conf (limited; not true split-horizon)."
    echo "Install systemd-resolved or dnsmasq for proper split-horizon DNS."
    exit 0
  fi
fi

remove_all
echo "Failed to apply split-horizon DNS: no backend succeeded." >&2
exit 1
