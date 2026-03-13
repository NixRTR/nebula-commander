#!/usr/bin/env bash

set -eu

SERVER="${NEBULA_COMMANDER_SERVER:-}"
NETWORK_ID="${NEBULA_NETWORK_ID:-}"
POLL_INTERVAL="${NEBULA_DNS_POLL_INTERVAL:-60}"
OUTPUT_DIR="${NEBULA_OUTPUT_DIR:-/etc/nebula}"
TOKEN_FILE="${NEBULA_DEVICE_TOKEN_FILE:-/etc/nebula-commander/token}"
ENROLL_CODE="${ENROLL_CODE:-}"

# Normalize SERVE_DNS to boolean (case-insensitive)
SERVE_DNS_VALUE="$(printf '%s' "${SERVE_DNS:-}" | tr '[:upper:]' '[:lower:]')"
case "${SERVE_DNS_VALUE}" in
  1|true|yes|on) SERVE_DNS=1 ;;
  *) SERVE_DNS=0 ;;
esac

if [ -z "${SERVER}" ]; then
  echo "NEBULA_COMMANDER_SERVER is required" >&2
  exit 1
fi

# Ensure token file exists or enroll once using ENROLL_CODE
if [ ! -f "${TOKEN_FILE}" ]; then
  if [ -z "${ENROLL_CODE}" ]; then
    echo "Token file not found and ENROLL_CODE not set. Mount an existing token file or set ENROLL_CODE to enroll." >&2
    exit 1
  fi
  mkdir -p "$(dirname "$(readlink -f "${TOKEN_FILE}")")"
  export NEBULA_COMMANDER_SERVER="${SERVER}"
  export NEBULA_DEVICE_TOKEN_FILE="${TOKEN_FILE}"
  if ! ncclient --server "${SERVER}" enroll --code "${ENROLL_CODE}"; then
    echo "Enroll failed" >&2
    exit 1
  fi
  if [ ! -f "${TOKEN_FILE}" ]; then
    echo "Enroll succeeded but token file was not created at ${TOKEN_FILE}" >&2
    exit 1
  fi
fi

# Start ncclient run in the background
export NEBULA_COMMANDER_SERVER="${SERVER}"
export NEBULA_DEVICE_TOKEN_FILE="${TOKEN_FILE}"
mkdir -p "${OUTPUT_DIR}"
ncclient --server "${SERVER}" run --output-dir "${OUTPUT_DIR}" >/dev/null 2>&1 &
NCCLIENT_PID=$!

cleanup() {
  if [[ -n "${DNSMASQ_PID:-}" ]] && kill -0 "${DNSMASQ_PID}" 2>/dev/null; then
    kill "${DNSMASQ_PID}" 2>/dev/null || true
  fi
  if kill -0 "${NCCLIENT_PID}" 2>/dev/null; then
    kill "${NCCLIENT_PID}" 2>/dev/null || true
  fi
  exit 0
}
trap cleanup TERM INT

DNSMASQ_CONF="/etc/dnsmasq.d/nebula.conf"
ETAG=""
DNSMASQ_PID=""

CONFIG_YAML="${OUTPUT_DIR%/}/config.yaml"

is_lighthouse_from_config() {
  local path="$1"
  [[ -f "${path}" ]] && grep -q "am_lighthouse: true" "${path}"
}

restart_dnsmasq() {
  local conf="$1"
  # Stop any existing dnsmasq instance in the container namespace.
  pkill dnsmasq 2>/dev/null || true
  # Run dnsmasq in the foreground so all logs go to the container logs.
  dnsmasq --no-daemon --conf-file="${conf}" &
  DNSMASQ_PID=$!
}

while true; do
  LIGHTHOUSE=0
  if [[ "${SERVE_DNS}" -eq 1 && -n "${NETWORK_ID}" ]] && is_lighthouse_from_config "${CONFIG_YAML}"; then
    LIGHTHOUSE=1
  fi

  if [[ "${LIGHTHOUSE}" -ne 1 ]]; then
    # Ensure dnsmasq is not running when this node is not a lighthouse.
    if [[ -n "${DNSMASQ_PID:-}" ]] && kill -0 "${DNSMASQ_PID}" 2>/dev/null; then
      kill "${DNSMASQ_PID}" 2>/dev/null || true
      wait "${DNSMASQ_PID}" 2>/dev/null || true
    fi
    DNSMASQ_PID=""
    sleep "${POLL_INTERVAL}"
    continue
  fi

  URL="${SERVER%/}/api/networks/${NETWORK_ID}/dns/dnsmasq.conf"
  TMP_HEADERS="$(mktemp)"
  TMP_BODY="$(mktemp)"

  CURL_ARGS=(-sS -D "${TMP_HEADERS}" -o "${TMP_BODY}" --max-time 30)
  if [[ -f "${TOKEN_FILE}" ]]; then
    TOKEN="$(tr -d '\n\r' < "${TOKEN_FILE}")"
    [[ -n "${TOKEN}" ]] && CURL_ARGS+=(-H "Authorization: Bearer ${TOKEN}")
  fi
  if [[ -n "${ETAG}" ]]; then
    CURL_ARGS+=(-H "If-None-Match: \"${ETAG}\"")
  fi

  HTTP_CODE="$(curl "${CURL_ARGS[@]}" -w '%{http_code}' "${URL}" || echo "000")"

  if [[ "${HTTP_CODE}" == "000" ]]; then
    echo "DNS poll error: curl failed" >&2
    rm -f "${TMP_HEADERS}" "${TMP_BODY}"
    sleep "${POLL_INTERVAL}"
    continue
  fi

  if [[ "${HTTP_CODE}" == "304" ]]; then
    # Config unchanged (ETag match). If we already have a config file and dnsmasq
    # is not running, restart it so it recovers from prior failures.
    rm -f "${TMP_HEADERS}" "${TMP_BODY}"
    if [[ -f "${DNSMASQ_CONF}" ]]; then
      if [[ -z "${DNSMASQ_PID:-}" ]] || ! kill -0 "${DNSMASQ_PID}" 2>/dev/null; then
        echo "DNS config unchanged (304); restarting dnsmasq with existing config."
        restart_dnsmasq "${DNSMASQ_CONF}"
      fi
    fi
    sleep "${POLL_INTERVAL}"
    continue
  fi

  if [[ "${HTTP_CODE}" != "200" ]]; then
    echo "DNS poll failed: HTTP ${HTTP_CODE} $(head -c 200 "${TMP_BODY}" 2>/dev/null)" >&2
    rm -f "${TMP_HEADERS}" "${TMP_BODY}"
    sleep "${POLL_INTERVAL}"
    continue
  fi

  # Extract ETag header if present
  ETAG_LINE="$(grep -i '^etag:' "${TMP_HEADERS}" | tail -n 1 || true)"
  if [[ -n "${ETAG_LINE}" ]]; then
    ETAG="$(printf '%s' "${ETAG_LINE#*:}" | tr -d ' \"\r\n')"
  fi

  CONTENT="$(cat "${TMP_BODY}")"
  rm -f "${TMP_HEADERS}" "${TMP_BODY}"

  mkdir -p "$(dirname "${DNSMASQ_CONF}")"
  printf '%s\n' "${CONTENT}" > "${DNSMASQ_CONF}"
  # Always ensure dnsmasq is running with the latest config. If it's not running,
  # restart it; if it is already running, leave it alone to avoid unnecessary restarts.
  if [[ -z "${DNSMASQ_PID:-}" ]] || ! kill -0 "${DNSMASQ_PID}" 2>/dev/null; then
    echo "Starting dnsmasq with updated config."
    restart_dnsmasq "${DNSMASQ_CONF}"
  fi

  sleep "${POLL_INTERVAL}"
done

