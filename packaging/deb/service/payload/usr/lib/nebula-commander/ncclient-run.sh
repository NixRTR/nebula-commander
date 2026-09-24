#!/bin/sh
# ExecStart wrapper for ncclient.service.
#
# Only reason this exists instead of a bare ExecStart=/usr/bin/ncclient run
# line: --accept-dns is a startup flag on the frozen ncclient CLI (client/
# ncclient.py), not something it re-reads from settings.json while running,
# so the desktop app's "Accept split-horizon DNS" toggle (client/linux/
# desktop.py) can only take effect on the next process start. This wrapper
# re-checks settings.json on every (re)start and adds the flag if set, so a
# `systemctl restart ncclient` after toggling it in the desktop app is
# enough - matches what the desktop app's Settings page already does after
# Save.
set -e

SETTINGS_FILE=/var/lib/ncclient/settings.json
ACCEPT_DNS_FLAG=""
if [ -f "$SETTINGS_FILE" ] && grep -q '"accept_dns"[[:space:]]*:[[:space:]]*true' "$SETTINGS_FILE"; then
    ACCEPT_DNS_FLAG="--accept-dns"
fi

exec /usr/bin/ncclient run --output-dir /var/lib/ncclient $ACCEPT_DNS_FLAG
