# ncclient Binary Distribution

This directory contains the PyInstaller configuration and build scripts for creating standalone executables of `ncclient` for Linux, Windows, and macOS.

## Prerequisites

```bash
pip install pyinstaller
```

## Building

### Quick Build (Current Platform)

```bash
# From the client/binaries directory
python build.py
```

This will create a single-file executable in `dist/ncclient` (or `dist/ncclient.exe` on Windows).

### Manual Build

```bash
pyinstaller ncclient.spec
```

## Testing

After building, test the executable:

```bash
# Linux/macOS
./dist/ncclient --help

# Windows
.\dist\ncclient.exe --help
```

## Distribution

The executables are standalone and include:
- Python interpreter
- All dependencies (requests, etc.)
- ncclient code

Users do NOT need Python installed to run these executables.

## Supported Platforms

The build system supports both x86_64 and ARM64 architectures:

- **Linux x86_64**: `ncclient-linux-amd64` (~15-20 MB)
- **Linux ARM64**: `ncclient-linux-arm64` (~15-20 MB) - Raspberry Pi, AWS Graviton, ARM servers
- **Windows x86_64**: `ncclient-windows-amd64.exe` (~8 MB)
- **Windows ARM64**: `ncclient-windows-arm64.exe` (~8 MB) - Snapdragon X, Surface Pro X
- **macOS x86_64**: `ncclient-macos-amd64` (~20-25 MB) - Intel Macs
- **macOS ARM64**: `ncclient-macos-arm64` (~20-25 MB) - M1/M2/M3/M4 Macs

## Cross-Platform Building

### Local Builds

PyInstaller executables must be built on the target platform:
- Build Linux binaries on Linux
- Build Windows binaries on Windows
- Build macOS binaries on macOS

### Automated Builds (GitHub Actions)

The repository includes a GitHub Actions workflow (`.github/workflows/build-ncclient-binaries.yml`) that automatically builds for all 6 platforms when you push a version tag:

```bash
git tag v0.1.5
git push origin v0.1.5
```

This will build and release binaries for all platforms, including ARM64 variants.

For more details on ARM64 builds, see `ARM64-BUILDS.md`.

## Cleaning

```bash
python build.py --clean
```

Or manually:
```bash
rm -rf build/ dist/ *.spec
```
