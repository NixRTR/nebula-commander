# Creating Releases with Binaries

This document describes how to create releases of Nebula Commander with pre-built `ncclient` binaries for Windows, Linux, and macOS.

## Overview

The repository includes a GitHub Actions workflow that automatically builds standalone executables for `ncclient` on multiple platforms. When you push a version tag, the workflow:

1. Builds binaries for Linux, Windows, macOS Intel, and macOS ARM
2. Runs automated tests on each platform
3. Creates a GitHub Release
4. Uploads all binaries and checksums to the release

## Quick Release Process

### 1. Prepare the Release

```bash
# Update version in client/pyproject.toml
# Change version = "0.1.4" to version = "0.1.5"

# Commit the change
git add client/pyproject.toml
git commit -m "Release v0.1.5"
```

### 2. Create and Push Tag

```bash
# Create annotated tag
git tag -a v0.1.5 -m "Release v0.1.5"

# Push commit and tag
git push origin main
git push origin v0.1.5
```

### 3. Wait for Builds

- Go to the **Actions** tab on GitHub
- Watch the "Build ncclient Binaries" workflow
- All 6 platforms build in parallel (~15-20 minutes total)

### 4. Verify Release

- Go to the **Releases** page
- Find your new release (e.g., `v0.1.5`)
- Verify all files are present:
  - `ncclient-linux-amd64`
  - `ncclient-linux-arm64`
  - `ncclient-windows-amd64.exe`
  - `ncclient-windows-arm64.exe`
  - `ncclient-macos-amd64`
  - `ncclient-macos-arm64`
  - `SHA256SUMS.txt`

## What Gets Released

### Binaries

| Platform | Filename | Size | Notes |
|----------|----------|------|-------|
| Linux (x86_64) | `ncclient-linux-amd64` | ~15-20 MB | Ubuntu-compatible, Intel/AMD |
| Linux (ARM64) | `ncclient-linux-arm64` | ~15-20 MB | Ubuntu-compatible, ARM64/aarch64 |
| Windows (x86_64) | `ncclient-windows-amd64.exe` | ~8 MB | Windows 10/11, Intel/AMD |
| Windows (ARM64) | `ncclient-windows-arm64.exe` | ~8 MB | Windows 11 ARM, Snapdragon/ARM |
| macOS Intel | `ncclient-macos-amd64` | ~20-25 MB | Intel Macs |
| macOS ARM | `ncclient-macos-arm64` | ~20-25 MB | M1/M2/M3/M4 Macs |

### Checksums

`SHA256SUMS.txt` contains SHA256 checksums for all binaries. Users can verify downloads:

```bash
# Linux/macOS
sha256sum -c SHA256SUMS.txt

# Windows (PowerShell)
Get-FileHash ncclient-windows-amd64.exe -Algorithm SHA256
```

## Testing Before Release

### Option 1: Build Locally

```bash
cd client/binaries
python build.py --test
```

### Option 2: Test in GitHub Actions

Push to `main` without a tag:

```bash
git push origin main
```

This triggers builds without creating a release. Download artifacts from the Actions tab to test.

### Option 3: Manual Workflow Run

1. Go to Actions tab
2. Select "Build ncclient Binaries"
3. Click "Run workflow"
4. Select branch and run

## Versioning

Follow semantic versioning (semver):
- **Major** (1.0.0): Breaking changes
- **Minor** (0.1.0): New features, backward compatible
- **Patch** (0.1.1): Bug fixes

Examples:
- `v0.1.5` → `v0.1.6`: Bug fix
- `v0.1.5` → `v0.2.0`: New feature
- `v0.1.5` → `v1.0.0`: Breaking change

## Release Notes

GitHub automatically generates release notes from commits. To improve them:

### Use Conventional Commits

```bash
git commit -m "feat: add support for custom ports"
git commit -m "fix: resolve token expiration issue"
git commit -m "docs: update installation guide"
```

### Add Manual Notes

After the release is created, edit it on GitHub to add:
- Highlights of new features
- Breaking changes
- Upgrade instructions
- Known issues

## Troubleshooting

### Build Fails

Check the Actions tab for error logs. Common issues:

1. **Import errors**: Update `hiddenimports` in `client/binaries/ncclient.spec`
2. **Test failures**: Fix tests or update `client/binaries/build.py`
3. **PyInstaller errors**: Check PyInstaller compatibility

### Release Not Created

- Verify tag starts with `v` (e.g., `v0.1.5`, not `0.1.5`)
- Check workflow permissions in repo settings
- Ensure `GITHUB_TOKEN` has release permissions

### Missing Binaries

- Check all build jobs completed successfully
- Verify artifact upload steps succeeded
- Check release creation step logs

## Pre-release Versions

For beta/alpha releases:

```bash
# Tag as pre-release
git tag -a v0.2.0-beta.1 -m "Beta release"
git push origin v0.2.0-beta.1
```

Then manually mark the release as "pre-release" on GitHub.

## Hotfix Process

For urgent fixes to a release:

```bash
# Create hotfix branch from tag
git checkout -b hotfix/v0.1.6 v0.1.5

# Make fixes
git commit -m "fix: critical security issue"

# Tag and push
git tag v0.1.6
git push origin hotfix/v0.1.6
git push origin v0.1.6

# Merge back to main
git checkout main
git merge hotfix/v0.1.6
git push origin main
```

## Workflow Configuration

The workflow is defined in `.github/workflows/build-ncclient-binaries.yml`.

### Triggers

- **Tags**: `v*` → Creates release
- **Push to main**: Builds only (no release)
- **Pull requests**: Builds when client code changes
- **Manual**: Via Actions tab

### Customization

See `.github/workflows/README.md` for details on customizing:
- Python version
- Build platforms
- Release settings
- Test configuration

## Distribution

### Direct Download

Point users to the Releases page:
```
https://github.com/NixRTR/nebula-commander/releases
```

### Installation Instructions

Update your README with download links:

```markdown
## Installation

### Pre-built Binaries

Download the latest release for your platform:

- [Linux (x86_64)](https://github.com/NixRTR/nebula-commander/releases/latest/download/ncclient-linux-amd64)
- [Windows (x86_64)](https://github.com/NixRTR/nebula-commander/releases/latest/download/ncclient-windows-amd64.exe)
- [macOS Intel](https://github.com/NixRTR/nebula-commander/releases/latest/download/ncclient-macos-amd64)
- [macOS ARM](https://github.com/NixRTR/nebula-commander/releases/latest/download/ncclient-macos-arm64)

Make executable (Linux/macOS):
\`\`\`bash
chmod +x ncclient-*
\`\`\`
```

## PyPI Releases

The binaries complement (don't replace) PyPI distribution:

```bash
# PyPI (requires Python)
pip install nebula-commander

# Binary (no Python required)
# Download from GitHub Releases
```

Both methods install the same `ncclient` tool.

## Checklist

Before creating a release:

- [ ] All tests pass locally
- [ ] Version bumped in `client/pyproject.toml`
- [ ] CHANGELOG updated (if you maintain one)
- [ ] Documentation updated
- [ ] Breaking changes documented
- [ ] Commit and push to `main`
- [ ] Create and push tag
- [ ] Monitor GitHub Actions build
- [ ] Verify release created with all files
- [ ] Test download and run on at least one platform
- [ ] Update PyPI package (optional, separate process)
- [ ] Announce release (Discord, Twitter, etc.)

## Support

If builds fail or you need help:
1. Check `.github/workflows/README.md`
2. Review Actions logs
3. Open an issue on GitHub

---

**Ready to release?** Follow the Quick Release Process above! 🚀
