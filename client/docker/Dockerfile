# -----------------------------------------------------------------------------
# Stage 1: Build ncclient binary with Python 3.13 and PyInstaller
# -----------------------------------------------------------------------------
FROM python:3.13-slim AS builder

WORKDIR /app

# Copy full client tree (build context is client/)
COPY . /app/client/

# Install build deps: binutils (for objdump) + PyInstaller and deps
RUN apt-get update && apt-get install -y binutils && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir pyinstaller requests

# Build: run from binaries/ so ncclient.spec's paths resolve; PYTHONPATH so "client" package is found
ENV PYTHONPATH=/app
RUN cd /app/client/binaries && python build.py

# -----------------------------------------------------------------------------
# Stage 2: Runtime image with ncclient binary, Nebula, and entrypoint
# -----------------------------------------------------------------------------
FROM debian:stable-slim

RUN apt-get update && apt-get install -y \
    dnsmasq \
    curl \
    ca-certificates \
    procps \
    xz-utils \
    && rm -rf /var/lib/apt/lists/*

# Install s6-overlay v3
ARG S6_OVERLAY_VERSION=v3.2.2.0
ADD https://github.com/just-containers/s6-overlay/releases/download/${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp/
ADD https://github.com/just-containers/s6-overlay/releases/download/${S6_OVERLAY_VERSION}/s6-overlay-x86_64.tar.xz /tmp/
RUN tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz \
    && tar -C / -Jxpf /tmp/s6-overlay-x86_64.tar.xz \
    && rm -f /tmp/s6-overlay-noarch.tar.xz /tmp/s6-overlay-x86_64.tar.xz

# Copy ncclient binary from builder
COPY --from=builder /app/client/binaries/dist/ncclient /usr/local/bin/ncclient
RUN chmod +x /usr/local/bin/ncclient

# Download latest Nebula release (linux/amd64) from GitHub at build time
RUN curl -sSL -o /tmp/nebula.tar.gz \
    "https://github.com/slackhq/nebula/releases/latest/download/nebula-linux-amd64.tar.gz" \
    && tar -xzf /tmp/nebula.tar.gz -C /tmp \
    && NEBULA_BIN=$(find /tmp -maxdepth 2 -type f -name nebula 2>/dev/null | head -1) \
    && install -m 755 "$NEBULA_BIN" /usr/local/bin/nebula \
    && rm -rf /tmp/nebula.tar.gz /tmp/nebula /tmp/nebula-linux-amd64

ENV NEBULA_COMMANDER_SERVER=""
ENV NEBULA_DNS_POLL_INTERVAL="60"
ENV NEBULA_OUTPUT_DIR="/etc/nebula"
# NEBULA_DEVICE_TOKEN_FILE: set at runtime; path to device token file (default in s6 scripts: /etc/nebula-commander/token). Not set in image to avoid ENV-secrets linter.

# s6-overlay services for ncclient and dnsmasq
RUN mkdir -p /etc/s6-overlay/s6-rc.d/ncclient /etc/s6-overlay/s6-rc.d/dnsmasq /etc/s6-overlay/s6-rc.d/user/contents.d
# Build context root is nebula-commander/client; the s6 scripts live under docker/s6.
COPY docker/s6/ncclient/run /etc/s6-overlay/s6-rc.d/ncclient/run
COPY docker/s6/dnsmasq/run  /etc/s6-overlay/s6-rc.d/dnsmasq/run
RUN chmod +x /etc/s6-overlay/s6-rc.d/ncclient/run /etc/s6-overlay/s6-rc.d/dnsmasq/run \
    && printf 'longrun\n' > /etc/s6-overlay/s6-rc.d/ncclient/type \
    && printf 'longrun\n' > /etc/s6-overlay/s6-rc.d/dnsmasq/type \
    && touch /etc/s6-overlay/s6-rc.d/user/contents.d/ncclient \
    && touch /etc/s6-overlay/s6-rc.d/user/contents.d/dnsmasq

# Host networking is expected at runtime; dnsmasq will bind inside the host namespace.
ENV S6_KEEP_ENV=1
ENTRYPOINT ["/init"]
