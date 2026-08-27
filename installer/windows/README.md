# Nebula Commander Windows MSI Installer

WiX 5 installer that installs **ncclient** (CLI), **ncclient-tray** (unelevated
configuration/control UI), and **ncclient-service** (the `NebulaCommanderService`
Windows Service that actually runs the VPN, as LocalSystem) to
`%ProgramFiles%\Nebula Commander\`, with optional PATH and Start Menu shortcuts.

## Prerequisites

- [.NET SDK](https://dotnet.microsoft.com/download) (required for the WiX dotnet tool)
- [WiX Toolset 5](https://wixtoolset.org/docs/intro/) (e.g. `dotnet tool install --global wix --version 5.0.2` or install from [releases](https://github.com/wixtoolset/wix/releases))
- The three executables in `redist/`:
  - `redist/ncclient.exe`
  - `redist/ncclient-tray.exe`
  - `redist/ncclient-service.exe`

## Building locally

1. Copy or build the three exes into `installer/windows/redist/`:
   - `ncclient.exe` (from `client/binaries/dist/ncclient.exe` after PyInstaller build)
   - `ncclient-tray.exe` and `ncclient-service.exe` (from `client/windows/dist/` after
     `python client/windows/build.py`)
2. If you installed WiX 5 via `dotnet tool install -g wix --version 5.0.2`, add the Util extension once (use version 5.0.0 so it matches WiX 5; the default pulls 7.x which is incompatible):
   ```powershell
   wix extension add -g WixToolset.Util.wixext/5.0.0
   ```
3. From `installer/windows/` run:

   ```powershell
   wix build Product.wxs -ext WixToolset.Util.wixext -o NebulaCommander-windows-amd64.msi -d Version=0.1.12 -arch x64
   ```

   Replace `0.1.12` with the version you are building (e.g. from tag `v0.1.12`).

Output: `NebulaCommander-windows-amd64.msi`.

## What the installer does

- Installs all three exes to **Program Files\Nebula Commander** (per-machine).
- Registers and starts **`NebulaCommanderService`** (start type: Automatic,
  runs as LocalSystem) - this is what actually polls Nebula Commander, runs
  Nebula, and applies split-horizon DNS. It's stopped on upgrade/uninstall and
  removed on uninstall.
- Creates `%ProgramData%\nebula-commander\` (shared settings, DPAPI-encrypted
  device token, status file, downloaded Nebula binary, and Nebula's own runtime
  files) with an ACL granting local `Users` modify rights, so the unelevated
  tray can write there while the LocalSystem service reads/writes freely.
- Grants local `Authenticated Users` start/stop/query-status rights on the
  service (via a deferred `sc sdset` custom action, since only Administrators
  can control a service by default) - this is what lets the tray's Start/Stop/
  Restart Service menu items work without a UAC prompt. **Verify on a real
  install**: `sc sdshow NebulaCommanderService` should show an ACE for
  `Authenticated Users`, and using those menu items from the tray shouldn't
  trigger UAC.
- **Optional feature**: "Add install directory to PATH" so `ncclient` works from any command prompt.
- **Start Menu** shortcuts: "Nebula Commander (CLI)" and "Nebula Commander Tray".
- **Add or Remove Programs**: full uninstall, including PATH removal if that feature was installed and the service/its data folder as described above.

## CI

The GitHub Actions workflow builds the MSI after building the Windows ncclient, tray, and service exes, then uploads `NebulaCommander-windows-amd64.msi` to the release. See `.github/workflows/build-ncclient-binaries.yml`.
