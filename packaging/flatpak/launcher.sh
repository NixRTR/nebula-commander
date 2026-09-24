#!/bin/sh
# Launcher for the GTK4/libadwaita desktop app inside the Flatpak sandbox.
# Runs the .py file directly (not `python3 -m client.linux.desktop`) so
# client/linux/desktop.py's own _ensure_path() can find and insert its
# parent directory onto sys.path, making `import client.xxx` resolve
# without needing PYTHONPATH set here - same reasoning as the .deb
# package's /usr/bin/nebula-commander-desktop wrapper.
exec python3 /app/share/nebula-commander-desktop/client/linux/desktop.py "$@"
