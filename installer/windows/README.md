# Nebula Commander Windows MSI Installer

WiX v4 installer that installs **ncclient** (CLI) and **ncclient-tray** (system tray) to `%ProgramFiles%\Nebula Commander\`, with optional PATH and Start Menu shortcuts.

## Prerequisites

- [WiX Toolset v4](https://wixtoolset.org/docs/intro/) (e.g. `winget install WiXToolset.WiX` or install from [releases](https://github.com/wixtoolset/wix4/releases))
- The two executables in `redist/`:
  - `redist/ncclient.exe`
  - `redist/ncclient-tray.exe`

## Building locally

1. Copy or build the two exes into `installer/windows/redist/`:
   - `ncclient.exe` (from `client/binaries/dist/ncclient.exe` after PyInstaller build)
   - `ncclient-tray.exe` (from `client/windows/dist/ncclient-tray.exe` after tray build)
2. From `installer/windows/` run:

   ```powershell
   wix build Product.wxs -ext WixToolset.Util.wixext -o NebulaCommander-windows-amd64.msi -d Version=0.1.12 -arch x64
   ```

   Replace `0.1.12` with the version you are building (e.g. from tag `v0.1.12`).

Output: `NebulaCommander-windows-amd64.msi`.

## What the installer does

- Installs both exes to **Program Files\Nebula Commander** (per-machine).
- **Optional feature**: "Add install directory to PATH" so `ncclient` works from any command prompt.
- **Start Menu** shortcuts: "Nebula Commander (CLI)" and "Nebula Commander Tray".
- **Add or Remove Programs**: full uninstall, including PATH removal if that feature was installed.

## CI

The GitHub Actions workflow builds the MSI after building the Windows ncclient and tray exes, then uploads `NebulaCommander-windows-amd64.msi` to the release. See `.github/workflows/build-ncclient-binaries.yml`.
