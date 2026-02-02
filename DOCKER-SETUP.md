# Docker Images Setup Guide

This guide explains how to set up automated Docker image builds for Nebula Commander.

## Overview

GitHub Actions automatically builds and pushes Docker images to GitHub Container Registry (ghcr.io) for:
- **Backend**: FastAPI application with nebula-cert
- **Frontend**: React SPA served by nginx

## What's Configured

### Images
- `ghcr.io/nixrtr/nebula-commander-backend:latest`
- `ghcr.io/nixrtr/nebula-commander-frontend:latest`

### Architectures
- linux/amd64 (Intel/AMD)
- linux/arm64 (ARM64/aarch64 - Raspberry Pi, AWS Graviton, etc.)

### Workflow
- **File**: `.github/workflows/build-docker-images.yml`
- **Triggers**:
  - Version tags (`v*`) → Build and push with version tags
  - Manual trigger (via Actions tab)

## First-Time Setup

### 1. Enable GitHub Container Registry

GitHub Container Registry is automatically available for your repository. No additional setup needed!

### 2. Make Images Public (Optional but Recommended)

After the first build, make the images public so users can pull without authentication:

1. Go to https://github.com/orgs/NixRTR/packages (or your org/user packages)
2. Find `nebula-commander-backend` and `nebula-commander-frontend`
3. Click each package
4. Click "Package settings" (gear icon)
5. Scroll to "Danger Zone"
6. Click "Change visibility" → "Public"
7. Confirm

### 3. Test the Workflow

#### Option A: Create a Tag (Recommended)

```bash
git tag v0.1.5
git push origin v0.1.5
```

This will create images tagged with `0.1.5`, `0.1`, `0`, and `latest`.

#### Option B: Manual Trigger

1. Go to Actions tab
2. Select "Build and Push Docker Images"
3. Click "Run workflow"
4. Select branch and run

## Image Tags

The workflow automatically creates multiple tags for each release:

### For Version Tags (e.g., `v1.2.3`)
- `1.2.3` (full version)
- `1.2` (major.minor)
- `1` (major)
- `latest` (always updated to newest release)

## Using the Images

### Pull Pre-built Images

```bash
# Latest version
docker pull ghcr.io/nixrtr/nebula-commander-backend:latest
docker pull ghcr.io/nixrtr/nebula-commander-frontend:latest

# Specific version
docker pull ghcr.io/nixrtr/nebula-commander-backend:1.2.3
docker pull ghcr.io/nixrtr/nebula-commander-frontend:1.2.3
```

### Run with Docker Compose

```bash
cd docker
cp .env.example .env
# Edit .env to set JWT_SECRET_KEY

# Pull and start
docker compose pull
docker compose up -d
```

## Build Process

### What Happens During Build

1. **Checkout code**
2. **Set up Docker Buildx** (for multi-arch builds)
3. **Login to ghcr.io** (using GITHUB_TOKEN)
4. **Extract metadata** (generate tags and labels)
5. **Build images** for amd64 and arm64
6. **Push to registry** (if not a PR)
7. **Cache layers** (for faster subsequent builds)

### Build Time

- **Backend**: ~3-5 minutes
- **Frontend**: ~5-7 minutes (includes npm build)
- **Total**: ~10 minutes (parallel builds)

## Workflow Features

### ✅ Multi-Architecture
Builds for both amd64 and arm64 automatically.

### ✅ Layer Caching
Uses GitHub Actions cache to speed up builds:
- First build: ~10 minutes
- Subsequent builds: ~3-5 minutes (with cache)

### ✅ Automatic Tagging
Creates multiple tags based on the trigger:
- Version tags for releases
- `latest` for main branch
- Branch names for feature branches
- PR numbers for pull requests

### ✅ Parallel Builds
Backend and frontend build simultaneously.

### ✅ Security
- Uses `GITHUB_TOKEN` (automatically provided)
- No additional secrets needed
- Images can be made public or kept private

## Troubleshooting

### Build Fails

Check the Actions tab for logs. Common issues:

1. **Dockerfile errors**: Fix syntax in `docker/backend/Dockerfile` or `docker/frontend/Dockerfile`
2. **Build context**: Make sure files exist at the paths specified in Dockerfiles
3. **Dependencies**: Check that all dependencies are available

### Images Not Visible

1. Check if build succeeded in Actions tab
2. Go to https://github.com/orgs/NixRTR/packages
3. Make sure images are set to "Public" if you want them accessible without auth

### Can't Pull Images

If you get "unauthorized" errors:
1. Make sure images are public (see "Make Images Public" above)
2. Or authenticate: `echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin`

### Wrong Architecture

Docker automatically pulls the correct architecture. To verify:

```bash
docker image inspect ghcr.io/nixrtr/nebula-commander-backend:latest | grep Architecture
```

Should show `amd64` on Intel/AMD or `arm64` on ARM systems.

## Updating Images

### For New Releases

```bash
# Bump version in your code
# Then create and push a tag
git tag v0.1.6
git push origin v0.1.6
```

Images will be automatically built and tagged with `0.1.6`, `0.1`, `0`, and `latest`.

### For Development

Use manual workflow trigger or create a pre-release tag:

```bash
# Pre-release tag
git tag v0.2.0-beta.1
git push origin v0.2.0-beta.1
```

## Manual Build (Local)

If you need to build locally:

```bash
cd docker

# Single architecture (your platform)
docker compose build

# Multi-architecture (requires buildx)
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/backend/Dockerfile \
  -t ghcr.io/nixrtr/nebula-commander-backend:latest \
  .
```

## Cost

GitHub Actions is free for public repositories. For private repositories:
- Linux runners: 1x multiplier
- ~10 minutes per build
- 2000 free minutes/month for private repos

## Documentation

- **Docker README**: `docker/README.md`
- **Workflow file**: `.github/workflows/build-docker-images.yml`
- **Docker Compose**: `docker/docker-compose.yml`

## Next Steps

1. ✅ Push workflow to GitHub
2. ✅ Trigger a build (push to main or create a tag)
3. ✅ Make images public in GitHub packages
4. ✅ Update main README with Docker installation instructions
5. ✅ Test pulling and running images

---

**Docker images are now automated!** 🐳
