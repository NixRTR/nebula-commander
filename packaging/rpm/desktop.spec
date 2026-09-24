# Plain Python source, not a frozen binary (see packaging/deb's desktop
# control.in for why) - disable RPM's automatic Python bytecompile brp
# script so it doesn't try to precompile/own .pyc files under
# /usr/share/nebula-commander-desktop; bytecode is generated at runtime as
# needed instead, same as the .deb package.
%global __brp_python_bytecompile %{nil}

Name: nebula-commander-desktop
Version: %{_version}
Release: 1%{?dist}
Summary: Nebula Commander desktop app (GTK4/libadwaita)
License: GPL-3.0-or-later
URL: https://github.com/NixRTR/nebula-commander
BuildArch: noarch
Requires: python3
Requires: python3-gobject
Requires: gtk4
Requires: libadwaita
Requires: python3-jeepney
Requires: dbus
Recommends: nebula-commander-service

%description
GTK4 + libadwaita GUI for enrolling this device, viewing connection
status, and choosing which offered subnet routes/exit node to accept.
Talks to the ncclient systemd service's D-Bus API
(org.beardedtek.NebulaCommander1) rather than doing any networking or
direct file access itself - no shared group, file permissions, or
relogin step needed after install.

Ships as plain Python (not a frozen binary): GTK/PyGObject is well known
to freeze poorly with PyInstaller, so this depends on the distribution's
own python3-gobject/GTK4/libadwaita packages instead - the standard way
GTK apps are distributed via dnf/zypper.

No system tray icon: vanilla GNOME Shell has no tray icon support at
all, so this uses transient desktop notifications plus a normal window
instead, which works on every desktop with no extension required.

%install
rm -rf %{buildroot}
cp -a %{_stage_dir}/. %{buildroot}/

%files -f %{_filelist}

%post -f %{_post_script}

%postun -f %{_postun_script}

%changelog
* Mon Jan 01 2024 NixRTR <noreply@nixrtr.dev> - 0.0.0-1
- See https://github.com/NixRTR/nebula-commander/releases for release notes.
