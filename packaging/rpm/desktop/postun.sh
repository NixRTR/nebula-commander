#!/bin/sh
# Mirrors packaging/deb/desktop/DEBIAN/postrm - runs on any removal path
# (plain erase or the old version's cleanup during an upgrade), same as
# the .deb postrm's "remove" || "purge" gate covers unconditionally.
set -e

if command -v update-desktop-database >/dev/null; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null; then
    gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi

exit 0
