# Nebula Commander Frontend
# Node builder stage + nginx image

# Stage 1: Build React app
FROM node:20-alpine AS builder
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --legacy-peer-deps || npm install --legacy-peer-deps

COPY frontend/ .
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine

RUN apk add --no-cache curl

# Accept version as build arg (e.g. 0.1.5 from tag v0.1.5)
ARG VERSION=latest
# Set to 1 in CI (GitHub Actions) to download ncclient binaries from releases. Default 0 for local builds.
ARG DOWNLOAD_BINARIES=0

# Create downloads dir; optionally download ncclient binaries from GitHub releases (only when DOWNLOAD_BINARIES=1)
RUN mkdir -p /usr/share/nginx/html/downloads && \
    if [ "$DOWNLOAD_BINARIES" = "1" ]; then \
      cd /usr/share/nginx/html/downloads && \
      curl -fsSL -o ncclient-linux-amd64 "https://github.com/NixRTR/nebula-commander/releases/download/v${VERSION}/ncclient-linux-amd64" && \
      curl -fsSL -o ncclient-linux-arm64 "https://github.com/NixRTR/nebula-commander/releases/download/v${VERSION}/ncclient-linux-arm64" && \
      curl -fsSL -o ncclient-windows-amd64.exe "https://github.com/NixRTR/nebula-commander/releases/download/v${VERSION}/ncclient-windows-amd64.exe" && \
      curl -fsSL -o ncclient-tray-windows-amd64.exe "https://github.com/NixRTR/nebula-commander/releases/download/v${VERSION}/ncclient-tray-windows-amd64.exe" && \
      curl -fsSL -o ncclient-macos-amd64 "https://github.com/NixRTR/nebula-commander/releases/download/v${VERSION}/ncclient-macos-amd64" && \
      curl -fsSL -o ncclient-macos-arm64 "https://github.com/NixRTR/nebula-commander/releases/download/v${VERSION}/ncclient-macos-arm64" && \
      chmod +x ncclient-linux-amd64 ncclient-linux-arm64 ncclient-macos-amd64 ncclient-macos-arm64; \
    fi

COPY --from=builder /app/dist /usr/share/nginx/html
COPY docker/frontend/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost/health || exit 1
