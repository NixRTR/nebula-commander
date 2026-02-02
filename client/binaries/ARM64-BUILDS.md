# ARM64 Builds for ncclient

The build system now supports ARM64 (aarch64) architectures for Linux, Windows, and macOS!

## Supported ARM64 Platforms

### ✅ Linux ARM64
- **Architecture**: ARM64/aarch64
- **Devices**: Raspberry Pi 4/5, AWS Graviton, Oracle Ampere, ARM servers
- **File**: `ncclient-linux-arm64`
- **Build Method**: Docker with QEMU emulation on x86_64 runners

### ✅ Windows ARM64
- **Architecture**: ARM64
- **Devices**: Windows 11 ARM devices (Snapdragon X Elite/Plus, Surface Pro X)
- **File**: `ncclient-windows-arm64.exe`
- **Build Method**: Cross-compilation using Python ARM64

### ✅ macOS ARM64
- **Architecture**: ARM64 (Apple Silicon)
- **Devices**: M1, M2, M3, M4 Macs
- **File**: `ncclient-macos-arm64`
- **Build Method**: Native build on macOS ARM64 runners

## GitHub Actions Builds

The workflow automatically builds for all ARM64 platforms:

```yaml
# From .github/workflows/build-ncclient-binaries.yml
matrix:
  include:
    - platform: Linux (ARM64)
      arch: arm64
      asset_name: ncclient-linux-arm64
    
    - platform: Windows (ARM64)
      arch: arm64
      asset_name: ncclient-windows-arm64.exe
    
    - platform: macOS (ARM64)
      arch: arm64
      asset_name: ncclient-macos-arm64
```

### Build Methods

#### Linux ARM64
Uses Docker with QEMU emulation:
```bash
docker run --rm --platform linux/arm64 \
  -v "$PWD:/work" \
  python:3.11-slim \
  bash -c "pip install pyinstaller && python build.py"
```

**Pros:**
- Works on x86_64 GitHub runners
- No need for ARM64 runners
- Consistent build environment

**Cons:**
- Slower due to QEMU emulation (~4-5 minutes vs ~2-3 for native)
- Cannot run tests (emulated binaries may not execute properly)

#### Windows ARM64
Uses Python ARM64 architecture:
```bash
# Python setup with ARM64 architecture
python-version: '3.11'
architecture: arm64
```

**Pros:**
- Cross-compiles on x86_64 Windows runners
- PyInstaller detects target architecture from Python

**Cons:**
- Cannot run tests (ARM64 binary won't execute on x86_64 runner)
- Requires Python ARM64 build available

#### macOS ARM64
Native build on macOS ARM64 runners:
```bash
runs-on: macos-latest  # macos-14+ are ARM64
```

**Pros:**
- Native build, fastest
- Can run tests
- Best compatibility

**Cons:**
- Requires ARM64 runner (GitHub provides `macos-latest`)

## Local ARM64 Builds

### Linux ARM64

#### Option 1: Native (on ARM64 device)
```bash
# On Raspberry Pi, AWS Graviton, etc.
cd client/binaries
python3 build.py
```

#### Option 2: Docker (on x86_64)
```bash
# On x86_64 Linux with Docker
cd client/binaries
docker run --rm --platform linux/arm64 \
  -v "$PWD:/work" \
  -w /work \
  python:3.11-slim \
  bash -c "
    apt-get update && apt-get install -y binutils &&
    pip install -r requirements.txt &&
    pip install -r ../requirements.txt &&
    python build.py
  "
```

Output: `dist/ncclient` (ARM64)

### Windows ARM64

#### Option 1: Native (on Windows ARM device)
```powershell
# On Windows 11 ARM (Snapdragon X, Surface Pro X)
cd client\binaries
python build.py
```

#### Option 2: Cross-compile (on x86_64 Windows)
```powershell
# Install Python ARM64 from python.org
# Then build with ARM64 Python
py -3.11-arm64 -m pip install pyinstaller
py -3.11-arm64 build.py
```

Output: `dist\ncclient.exe` (ARM64)

### macOS ARM64

```bash
# On M1/M2/M3/M4 Mac
cd client/binaries
python3 build.py
```

Output: `dist/ncclient` (ARM64)

## Testing ARM64 Builds

### Can I test ARM64 binaries on x86_64?

**No**, ARM64 binaries will not run on x86_64 systems and vice versa.

### Testing Strategies

#### 1. Native Testing
Run on actual ARM64 hardware:
```bash
# On ARM64 device
./ncclient-linux-arm64 --help
./ncclient-linux-arm64 enroll --help
```

#### 2. Emulation (Linux only)
Use QEMU user-mode emulation:
```bash
# On x86_64 Linux
sudo apt-get install qemu-user-static
qemu-aarch64-static ./ncclient-linux-arm64 --help
```

#### 3. GitHub Actions
The workflow builds ARM64 but skips tests on cross-compiled platforms:
```yaml
- name: Run tests (native architectures only)
  if: matrix.arch == 'x64' || runner.os == 'macOS'
  run: python build.py --test
```

Tests run on:
- ✅ Linux x86_64
- ✅ Windows x86_64
- ✅ macOS Intel
- ✅ macOS ARM64 (native)
- ❌ Linux ARM64 (cross-compiled)
- ❌ Windows ARM64 (cross-compiled)

## Use Cases

### Linux ARM64
- **Raspberry Pi**: Home server, IoT gateway
- **AWS Graviton**: Cloud instances (cheaper than x86_64)
- **Oracle Cloud**: Free ARM instances
- **ARM Servers**: Data centers with ARM processors

### Windows ARM64
- **Snapdragon X Elite/Plus**: New Windows laptops (2024+)
- **Surface Pro X**: Microsoft ARM tablets
- **Windows Dev Kit 2023**: ARM development device

### macOS ARM64
- **M1/M2/M3/M4 Macs**: All Apple Silicon Macs (2020+)
- **Mac Mini**: Server/CI use
- **MacBook Pro/Air**: Development machines

## File Sizes

ARM64 binaries are similar in size to x86_64:

| Platform | x86_64 Size | ARM64 Size |
|----------|-------------|------------|
| Linux | ~15-20 MB | ~15-20 MB |
| Windows | ~8 MB | ~8 MB |
| macOS | ~20-25 MB | ~20-25 MB |

## Distribution

### Download Links (GitHub Releases)

```markdown
## ARM64 Binaries

- [Linux ARM64](https://github.com/NixRTR/nebula-commander/releases/latest/download/ncclient-linux-arm64)
- [Windows ARM64](https://github.com/NixRTR/nebula-commander/releases/latest/download/ncclient-windows-arm64.exe)
- [macOS ARM64](https://github.com/NixRTR/nebula-commander/releases/latest/download/ncclient-macos-arm64)
```

### Installation Instructions

**Linux ARM64:**
```bash
wget https://github.com/NixRTR/nebula-commander/releases/latest/download/ncclient-linux-arm64
chmod +x ncclient-linux-arm64
sudo mv ncclient-linux-arm64 /usr/local/bin/ncclient
```

**Windows ARM64:**
```powershell
# Download from GitHub Releases
# Place in C:\Program Files\ncclient\
# Add to PATH
```

**macOS ARM64:**
```bash
curl -L -o ncclient https://github.com/NixRTR/nebula-commander/releases/latest/download/ncclient-macos-arm64
chmod +x ncclient
sudo mv ncclient /usr/local/bin/
```

## Troubleshooting

### "cannot execute binary file: Exec format error"

You're trying to run an ARM64 binary on x86_64 (or vice versa). Download the correct architecture:
- x86_64/amd64: Intel/AMD processors
- ARM64/aarch64: ARM processors

Check your architecture:
```bash
# Linux
uname -m
# x86_64 = Intel/AMD
# aarch64 = ARM64

# macOS
uname -m
# x86_64 = Intel
# arm64 = Apple Silicon

# Windows (PowerShell)
$env:PROCESSOR_ARCHITECTURE
# AMD64 = Intel/AMD
# ARM64 = ARM
```

### Linux ARM64 build fails in GitHub Actions

Check the Docker build logs. Common issues:
- QEMU not set up correctly
- Missing dependencies in Docker image
- PyInstaller compatibility issues

### Windows ARM64 binary won't run

Make sure you're on Windows 11 ARM. Windows 10 ARM has limited support.

### macOS ARM64 vs x86_64

Apple Silicon Macs can run x86_64 binaries via Rosetta 2, but native ARM64 is faster and more efficient. Always prefer ARM64 on M1/M2/M3/M4 Macs.

## Performance

### ARM64 vs x86_64

**Linux:**
- AWS Graviton (ARM64): ~20-40% cheaper, similar performance
- Raspberry Pi 4/5: Lower performance, but excellent for edge/IoT

**Windows:**
- Snapdragon X Elite: Competitive with Intel/AMD, better battery life
- Surface Pro X: Good for mobile use

**macOS:**
- M1/M2/M3/M4: Significantly faster than Intel Macs, better battery

## Future: Universal Binaries

### macOS Universal Binary (x86_64 + ARM64)

PyInstaller doesn't natively support universal binaries. To create one:

```bash
# Build both architectures
python build.py  # on Intel Mac → x86_64
python build.py  # on ARM Mac → ARM64

# Combine with lipo
lipo -create ncclient-x86_64 ncclient-arm64 -output ncclient-universal
```

This is not currently automated but could be added to the workflow.

## Summary

✅ **6 platforms now supported:**
- Linux x86_64
- Linux ARM64
- Windows x86_64
- Windows ARM64
- macOS x86_64 (Intel)
- macOS ARM64 (Apple Silicon)

✅ **Automated builds** via GitHub Actions

✅ **No manual work required** - just push a tag!

---

**ARM64 builds are now part of every release!** 🚀
