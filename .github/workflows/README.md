# GitHub Actions Workflows

## build-ncclient-binaries.yml

Automatically builds standalone executables for `ncclient` on multiple platforms.

### Triggers

1. **Version Tags**: Push a tag like `v0.1.5` to build and create a GitHub Release
2. **Main Branch**: Builds on every push to `main` (for testing, no release)
3. **Pull Requests**: Builds when client code changes
4. **Manual**: Click "Run workflow" in the Actions tab

### Platforms Built

- **Linux x86_64**: `ncclient-linux-amd64` (Ubuntu, x86_64)
- **Linux ARM64**: `ncclient-linux-arm64` (Ubuntu, ARM64/aarch64)
- **Windows x86_64**: `ncclient-windows-amd64.exe` (Windows 10/11, x86_64)
- **Windows ARM64**: `ncclient-windows-arm64.exe` (Windows 11 ARM, ARM64)
- **macOS Intel**: `ncclient-macos-amd64` (Intel Macs, x86_64)
- **macOS ARM**: `ncclient-macos-arm64` (Apple Silicon M1/M2/M3/M4)

### Outputs

#### For Every Build
- Artifacts uploaded to the Actions run (available for 90 days)
- Test results in the workflow logs

#### For Tagged Releases (v*)
- GitHub Release created automatically
- All platform binaries attached to the release
- `SHA256SUMS.txt` with checksums for verification
- Release notes auto-generated from commits

### Usage

#### Create a Release

```bash
# Bump version in client/pyproject.toml
# Then tag and push
git tag v0.1.5
git push origin v0.1.5
```

The workflow will:
1. Build binaries for all 6 platforms (2 Linux, 2 Windows, 2 macOS)
2. Run tests on native x86_64 platforms
3. Create a GitHub Release
4. Upload all binaries and checksums

#### Manual Build

1. Go to Actions tab in GitHub
2. Select "Build ncclient Binaries"
3. Click "Run workflow"
4. Select branch and click "Run workflow"

Artifacts will be available in the workflow run.

#### Test Before Release

Push to `main` branch to build without creating a release:

```bash
git push origin main
```

Check the Actions tab to see if builds succeed on all platforms.

### Build Time

Typical build times:
- Linux x86_64: ~2-3 minutes
- Linux ARM64: ~4-5 minutes (Docker + QEMU emulation)
- Windows x86_64: ~3-4 minutes
- Windows ARM64: ~3-4 minutes
- macOS Intel: ~3-4 minutes
- macOS ARM: ~3-4 minutes

Total: ~15-20 minutes for all 6 platforms (parallel builds)

### Troubleshooting

#### Build Fails on One Platform

The workflow uses `fail-fast: false`, so other platforms will continue building even if one fails. Check the logs for the failed platform.

#### Tests Fail

The workflow runs `python build.py --test` on each platform. If tests fail, the build will fail. Check the test output in the workflow logs.

#### Artifacts Not Found

Make sure the `client/binaries/dist/` directory contains the expected executable after the build step.

#### Release Not Created

Releases are only created for tags starting with `v`. Make sure you pushed a tag:

```bash
git tag v0.1.5
git push origin v0.1.5
```

### Customization

Edit `.github/workflows/build-ncclient-binaries.yml` to:
- Change Python version (currently 3.11)
- Add/remove platforms
- Modify build flags
- Change release settings

### Security

The workflow uses `GITHUB_TOKEN` which is automatically provided by GitHub Actions. No additional secrets are required.

### Cost

GitHub Actions is free for public repositories. For private repositories, builds consume minutes from your account quota.
