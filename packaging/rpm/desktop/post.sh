#!/bin/sh
# Mirrors packaging/deb/desktop/DEBIAN/postinst.
set -e

if command -v update-desktop-database >/dev/null; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null; then
    gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi

exit 0
