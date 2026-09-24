# Version, release, arch, and the staged file tree are all injected via
# `rpmbuild --define` (see packaging/rpm/build.py) rather than sed-style
# textual token substitution - idiomatic for a CI-driven spec with no
# %prep/%build stage of its own (the ncclient binary is already frozen by
# client/binaries/build.py before this ever runs; this spec just packages
# it, mirroring packaging/deb/build.py's stage-then-archive approach).

# PyInstaller's frozen binary trips up rpmbuild's automatic debuginfo
# extraction (it has no conventional debug symbols to split out, and the
# binary layout confuses find-debuginfo.sh) - disabling debuginfo
# generation and the other brp-* post-install scripts entirely matches
# the .deb package, which does no debug-symbol handling either.
%global debug_package %{nil}
%global __os_install_post %{nil}

Name: nebula-commander-client
Version: %{_version}
Release: 1%{?dist}
Summary: Nebula Commander device client (ncclient) CLI
License: GPL-3.0-or-later
URL: https://github.com/NixRTR/nebula-commander

%description
Standalone, self-contained ncclient CLI binary (PyInstaller-frozen, no
Python runtime dependency): enroll a device with a one-time code, then
poll the Nebula Commander server for config/certs and manage subnet
route/exit node acceptance from the command line.

Install nebula-commander-service as well to run this as a systemd
service instead of by hand.

%install
rm -rf %{buildroot}
cp -a %{_stage_dir}/. %{buildroot}/

%files -f %{_filelist}

%changelog
* Mon Jan 01 2024 NixRTR <noreply@nixrtr.dev> - 0.0.0-1
- See https://github.com/NixRTR/nebula-commander/releases for release notes.
