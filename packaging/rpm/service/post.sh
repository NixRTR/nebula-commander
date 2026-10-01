#!/bin/sh
# %post scriptlet for nebula-commander-service - runs unconditionally on
# both fresh install and upgrade (RPM's %post doesn't need a dpkg-style
# "configure" argument check for that; $1 is 1 on install, 2+ on upgrade). Mirrors
# packaging/deb/service/DEBIAN/postinst's "configure" branch exactly - see
# that file for the fuller rationale on why each reload is needed.
set -e

if command -v systemd-tmpfiles >/dev/null; then
    systemd-tmpfiles --create /usr/lib/tmpfiles.d/ncclient.conf || true
fi

if [ -d /run/systemd/system ]; then
    systemctl daemon-reload || true
fi

# polkitd and dbus-daemon (or dbus-broker, aliased as dbus.service on
# RPM-based distros too) both only read their respective policy
# directories at their OWN startup - see the .deb postinst for the fuller
# explanation of why an explicit reload (with a try-restart fallback for
# polkit units shipping no ExecReload=) is required here.
if [ -d /run/systemd/system ] && systemctl is-active --quiet polkit; then
    systemctl reload polkit 2>/dev/null || systemctl try-restart polkit || true
fi
if [ -d /run/systemd/system ] && systemctl is-active --quiet dbus; then
    systemctl reload dbus || true
fi

# Upgrades: restart a running ncclient so the new binary takes over now, not
# at the next reboot - see the .deb postinst for the incident behind this.
if [ -d /run/systemd/system ]; then
    systemctl try-restart ncclient.service || true
fi

# $1 is 1 on a fresh install, 2+ on upgrade.
if [ "$1" = "1" ]; then
    echo ""
    echo "Nebula Commander service installed but not started."
    echo "Next steps:"
    echo "  1. Set NEBULA_COMMANDER_SERVER in /etc/default/ncclient, then enroll:"
    echo "       sudo ncclient enroll --server https://your-server --code YOUR-CODE"
    echo "     (or enroll via the nebula-commander-desktop app instead)"
    echo "  2. sudo systemctl enable --now ncclient"
    echo ""
    echo "In the nebula-commander-desktop app (if installed), any local user can"
    echo "view status; changes need membership in the sudo or wheel group."
    echo ""
fi

exit 0
