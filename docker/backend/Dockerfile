# Nebula Commander Backend
# Standard Python image + nebula-cert binary

FROM python:3.13-slim

# App version (from git tag in CI; e.g. 0.1.5)
ARG VERSION=latest
ENV VERSION=${VERSION}

# Install nebula-cert from GitHub release (required for certificate signing)
ARG NEBULA_VERSION=1.8.2
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && curl -sSL "https://github.com/slackhq/nebula/releases/download/v${NEBULA_VERSION}/nebula-linux-amd64.tar.gz" \
    | tar xz -C /tmp \
    && cp "$(find /tmp -name nebula-cert -type f | head -1)" /usr/local/bin/ \
    && chmod +x /usr/local/bin/nebula-cert \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/nebula* \
    && apt-get clean

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ /app/backend/

# Data directories (mounted as volume in production)
RUN mkdir -p /var/lib/nebula-commander/certs

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV NEBULA_COMMANDER_DATABASE_URL=sqlite+aiosqlite:////var/lib/nebula-commander/db.sqlite
ENV NEBULA_COMMANDER_CERT_STORE_PATH=/var/lib/nebula-commander/certs
ENV NEBULA_COMMANDER_SERVER_HOST=0.0.0.0
ENV NEBULA_COMMANDER_SERVER_PORT=8081

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8081/api/health')" || exit 1


# --proxy-headers trusts X-Forwarded-For/X-Forwarded-Proto to populate
# request.client and the URL scheme. Safe to trust from any peer here: this
# container has no published host port (see docker-compose.yml) and is only
# ever reachable from the frontend/nginx container on the compose network,
# which already sets these headers correctly from the real client IP.
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8081", "--proxy-headers", "--forwarded-allow-ips=*"]
