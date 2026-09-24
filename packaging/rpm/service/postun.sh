#!/bin/sh
# %postun scriptlet for nebula-commander-service. $1 == 0 means this is a
# genuine full removal (the last version of this package is gone), not an
# upgrade in progress (where $1 >= 1) - the closest RPM equivalent of
# dpkg's postrm "purge" gate. Mirrors packaging/deb/service/DEBIAN/postrm.
set -e

if [ "$1" = "0" ]; then
    if [ -d /run/systemd/system ]; then
        systemctl daemon-reload || true
        systemctl reload polkit 2>/dev/null || systemctl try-restart polkit 2>/dev/null || true
        systemctl reload dbus 2>/dev/null || true
    fi
    # Deliberately does not remove /var/lib/ncclient: it holds the device's
    # enrollment token/certs, which the admin should remove explicitly
    # rather than have an uninstall do silently.
fi

exit 0
