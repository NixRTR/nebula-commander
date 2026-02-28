# Nebula Commander

[![Release](https://img.shields.io/github/v/release/NixRTR/nebula-commander?include_prereleases=&sort=semver)](https://github.com/NixRTR/nebula-commander/releases)
[![Static Badge](https://img.shields.io/badge/documentation-nebulacdr.com-blue)](https://nebulacdr.com)
[![Static Badge](https://img.shields.io/badge/[matrix]-support-blue)](https://matrix.to/#/#nebula-commander-support:matrix.org)
[![Static Badge](https://img.shields.io/badge/[matrix]-development-blue)](https://matrix.to/#/#nebula-development-support:matrix.org)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/NixRTR/nebula-commander/build-ncclient-binaries.yml?label=Linux%20x86_64)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/NixRTR/nebula-commander/build-ncclient-binaries.yml?label=Linux%20arm64)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/NixRTR/nebula-commander/build-ncclient-binaries.yml?label=Windows)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/NixRTR/nebula-commander/build-ncclient-binaries.yml?label=Windows%20Tray)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/NixRTR/nebula-commander/build-ncclient-binaries.yml?label=Windows%20Installer)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/NixRTR/nebula-commander/build-ncclient-binaries.yml?label=MacOS%20Intel)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/NixRTR/nebula-commander/build-ncclient-binaries.yml?label=MacOS%20arm64)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/NixRTR/nebula-commander/build-docker-images.yml?label=Backend)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/NixRTR/nebula-commander/build-docker-images.yml?label=Frontend)
![GitHub Actions Workflow Status](https://img.shields.io/github/actions/workflow/status/NixRTR/nebula-commander/build-docker-images.yml?label=Keycloak)

---

## A **self-hosted** control plane for [Nebula](https://github.com/slackhq/nebula) overlay networks

### What it does

- **Networks & nodes** — Create networks, manage nodes, IP allocation, and certificates
- **Web UI** — React dashboard with OIDC (e.g. Keycloak) or dev token authentication
- **Device client (ncclient)** — `pip install nebula-commander` for enroll and run; see [client/README.md](client/README.md) and [ncclient documentation](https://nebulacdr.com/docs/usage/ncclient/)

### Status

**Implemented**

- Network creation
- Certificate generation
- config.yaml generation
- Basic firewall group rules
- Node management
- Audit logging
- Basic invitation system
- User management system

**Planned (v0.2.0)**

- Exit nodes
- Magic DNS implementation
- Client UI via web interface
- Stabilize client

---

### Quick start

#### Docker Compose (recommended)

Pre-built images are published to [GitHub Container Registry](https://github.com/orgs/NixRTR/packages). Full details: [docker/README.md](docker/README.md).

```bash
cd docker
cp .env.example .env
cp -r env.d.example env.d
# Edit env.d/backend: set JWT secret, ENCRYPTION_KEY, etc.
docker compose pull
docker compose up -d
```

The app is available at http://localhost (or your configured port). For OIDC with Keycloak:

```bash
docker compose -f docker-compose.yml -f docker-compose-keycloak.yml up -d
```

#### NixOS (experimental)

Import the module and enable the service. See [nix/module.nix](nix/module.nix) for options and [Server Installation: NixOS](https://nebulacdr.com/docs/installation/nixos/) for more detail.

```nix
services.nebula-commander.enable = true;
# Optional: services.nebula-commander.jwtSecretFile = "/run/secrets/nebula-commander-jwt";
# Optional: services.nebula-commander.debug = false;
```

### Reverse proxy

For HTTPS and a custom domain, put a reverse proxy (nginx, Traefik, Caddy) in front. Example nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name nebula.example.com;
    ssl_certificate     /etc/ssl/certs/nebula.example.com.crt;
    ssl_certificate_key /etc/ssl/private/nebula.example.com.key;

    location / {
        proxy_pass http://localhost:80;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

See [docker/README.md § Reverse Proxy](docker/README.md#reverse-proxy) for more.

---

### Development setup

**Backend**

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r backend/requirements.txt
export NEBULA_COMMANDER_DATABASE_URL="sqlite+aiosqlite:///./backend/db.sqlite"
export NEBULA_COMMANDER_CERT_STORE_PATH="./backend/certs"
# Required: encryption key. Generate once:
# python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
export NEBULA_COMMANDER_ENCRYPTION_KEY="your-fernet-key-here"
export DEBUG=true
python -m uvicorn backend.main:app --reload --port 8081
```

**Frontend**

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 (dev token when backend is in debug mode). See [Development: Setup](https://nebulacdr.com/docs/development/setup/) for more.

---

### Production suggestions

- **Secrets** — Use `NEBULA_COMMANDER_JWT_SECRET_FILE` and `NEBULA_COMMANDER_ENCRYPTION_KEY_FILE` (or env from a secrets manager) instead of inline env.
- **HTTPS** — Serve via a reverse proxy with TLS; set `NEBULA_COMMANDER_PUBLIC_URL` to your public URL.
- **OIDC** — Use Keycloak (or another OIDC provider) instead of dev tokens; configure `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, and client secret.
- **CORS** — Set `NEBULA_COMMANDER_CORS_ORIGINS` to your front-end origin(s).
- **Backups** — Back up the data volume (SQLite and cert store) regularly. See [docker/README.md § Data Persistence](docker/README.md#data-persistence).
- **Upgrades** — For encryption-at-rest migration from older deployments, see [notes/SECURITY_UPGRADES.md](notes/SECURITY_UPGRADES.md).

---

### Configuration

Env prefix: `NEBULA_COMMANDER_`. Key options: `DATABASE_URL`, `CERT_STORE_PATH`, **`ENCRYPTION_KEY`** or **`ENCRYPTION_KEY_FILE`** (required), `JWT_SECRET_KEY` or `JWT_SECRET_FILE`, `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `DEBUG`. Full list and examples: [docker/env.d.example/backend](docker/env.d.example/backend) and [Server Configuration](https://nebulacdr.com/docs/configuration/).

### API

Base path `/api`. OpenAPI at `/api/docs` when the backend is running.

### Contributing

Contributions welcome; prefer small, focused PRs.

### License

See [LICENSE.md](LICENSE.md). Backend and frontend: MIT. Client (ncclient): GPLv3 or later.
