# Nebula Commander Windows MSI Installer

WiX 5 installer that installs **ncclient** (CLI), **NebulaCommanderApp**
(the windowed WinUI 3 app - side-tab Status/Enrollment/Settings UI, minimizes
to tray on close; the only GUI client), and **ncclient-service**
(the `NebulaCommanderService` Windows Service that actually runs the VPN, as
LocalSystem) to `%ProgramFiles%\Nebula Commander\`, with optional PATH and
Start Menu shortcuts.

## Prerequisites

- [.NET SDK](https://dotnet.microsoft.com/download) (required for the WiX dotnet tool, and to publish NebulaCommanderApp.exe)
- [WiX Toolset 5](https://wixtoolset.org/docs/intro/) (e.g. `dotnet tool install --global wix --version 5.0.2` or install from [releases](https://github.com/wixtoolset/wix/releases))
- The three executables in `redist/`:
  - `redist/ncclient.exe`
  - `redist/ncclient-service.exe`
  - `redist/NebulaCommanderApp.exe`

## Building locally

1. Copy or build the exes into `installer/windows/redist/`:
   - `ncclient.exe` (from `client/binaries/dist/ncclient.exe` after PyInstaller build)
   - `ncclient-service.exe` (from `client/windows/dist/` after
     `python client/windows/build.py`)
   - `NebulaCommanderApp.exe` (from `client/windows-app/bin/Release/net10.0-windows*/win-x64/publish/NebulaCommanderApp.exe`
     after `dotnet publish -c Release -r win-x64` from `client/windows-app/`)
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
- Creates `%ProgramData%\nebula-commander\` (settings, DPAPI-encrypted
  device token, status file, the service-managed Nebula install, and Nebula's
  own runtime files - `config.yaml` contains the node's private key) as
  **SYSTEM/Administrators-only**, with a protected DACL so nothing is inherited
  from `%ProgramData%`. The app never touches this folder; it goes through the
  service's named pipe. The service also re-applies this ACL to the whole tree
  on every start (`client/windows/harden.py`), which is what secures installs
  upgraded from versions that granted local `Users` full control here.
- Sets the service's ACL (deferred `sc sdset` custom action) so
  `Authenticated Users` can only **query** it (status/PID). Start/Stop/Restart
  need an elevated administrator. Verify with `sc sdshow
  NebulaCommanderService`: the `AU` ACE should be `CCLCSWLORC` (no `RP`/`WP`).
- Nebula itself isn't bundled: on first start the service downloads the
  official `slackhq/nebula` Windows release, verifies its SHA256 against the
  release's `SHASUM256.txt`, and installs the whole archive (`nebula.exe`,
  `nebula-cert.exe`, `dist\` incl. wintun) into the protected folder.
- **Optional feature**: "Add install directory to PATH" so `ncclient` works from any command prompt.
- **Finish dialog**: "Launch Nebula Commander now" checkbox launches `NebulaCommanderApp.exe`.
- **Start Menu** shortcuts: "Nebula Commander (CLI)" and "Nebula Commander" (the windowed app).
- **Add or Remove Programs**: full uninstall, including PATH removal if that feature was installed and the service/its data folder as described above.

## CI

The GitHub Actions workflow builds the MSI after building the Windows ncclient, service, and windowed-app exes, then uploads `NebulaCommander-windows-amd64.msi` to the release. See `.github/workflows/build-ncclient-binaries.yml`.
