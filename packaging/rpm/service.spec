Name: nebula-commander-service
Version: %{_version}
Release: 1%{?dist}
Summary: Nebula Commander device client systemd service
License: GPL-3.0-or-later
URL: https://github.com/NixRTR/nebula-commander
BuildArch: noarch
Requires: nebula-commander-client = %{version}-%{release}
Requires: nebula
Requires: polkit
# openSUSE names the D-Bus package dbus-1 (see desktop.spec).
Requires: (dbus or dbus-1)

%description
Runs ncclient as a systemd service (ncclient.service) as root, polling the
Nebula Commander server for config/certs and driving the Nebula binary.
Depends on the distribution's own packaged 'nebula' rather than bundling a
separately-fetched binary.

Exposes a system D-Bus service (org.beardedtek.NebulaCommander1) that the
optional nebula-commander-desktop package talks to for status/settings/
enrollment/route management, authorized per-call via polkit for any active
local session - no shared group, file permissions, or relogin step needed.
Also installs a polkit rule letting an active local session start/stop/
restart this one service without a password prompt.

%install
rm -rf %{buildroot}
cp -a %{_stage_dir}/. %{buildroot}/

%files -f %{_filelist}
%config(noreplace) /etc/default/ncclient

%post -f %{_post_script}

%postun -f %{_postun_script}

%changelog
* Mon Jan 01 2024 NixRTR <noreply@nixrtr.dev> - 0.0.0-1
- See https://github.com/NixRTR/nebula-commander/releases for release notes.
