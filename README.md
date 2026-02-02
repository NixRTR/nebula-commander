# Nebula Commander

A self-hosted control plane for Nebula overlay networks, similar to [defined.net](https://www.defined.net/).

## Overview

Nebula Commander provides a centralized management interface for [Nebula](https://github.com/slackhq/nebula) mesh VPN networks. It simplifies the process of creating, configuring, and managing Nebula networks and their nodes.

## Features

- **Network Management**: Create and manage multiple Nebula overlay networks
- **Certificate Management**: Built-in CA; sign host certificates with betterkeys (client-generated keypairs)
- **IP Allocation**: Subnet-based IP allocation with optional suggested IPs for lighthouses
- **Web Dashboard**: React UI for networks and nodes
- **OIDC Authentication**: Integrate with Authelia, Authentik, or any OIDC provider
- **Node Monitoring**: Heartbeat endpoint for node status and last_seen
- **NixOS Module**: Deploy as a NixOS service
- **Device client (ncclient)**: dnclient/dnclientd-style enrollment, polling, and orchestration — install with `pip install nebula-commander` to get the `ncclient` command; enroll once with a code, then run a daemon that pulls config and certs and optionally starts/restarts the Nebula process (see [client/README.md](client/README.md))

## Status

This project is in early development. Core certificate and network APIs are implemented.

## Installation

### Development

**Backend** (run from repo root)

```bash
cd nebula-commander
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r backend/requirements.txt
# Optional: install nebula-cert (e.g. from Nix: nix shell nixpkgs#nebula)
export NEBULA_COMMANDER_DATABASE_URL="sqlite+aiosqlite:///./backend/db.sqlite"
export NEBULA_COMMANDER_CERT_STORE_PATH="./backend/certs"
export DEBUG=true
python -m uvicorn backend.main:app --reload --port 8081
```

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. With backend in debug mode, the frontend will obtain a dev token automatically.

### NixOS

Add the Nebula Commander NixOS module and enable the service:

```nix
# In your NixOS config (e.g. configuration.nix)
{ config, ... }:

{
  imports = [
    /path/to/nebula-commander/nix/module.nix
    # Or from a flake: nebula-commander.nixosModules.default
  ];

  services.nebula-commander = {
    enable = true;
    backendPort = 8081;
    databasePath = "/var/lib/nebula-commander/db.sqlite";
    certStorePath = "/var/lib/nebula-commander/certs";
    # Optional: JWT secret file (e.g. from sops-nix)
    # jwtSecretFile = config.sops.secrets."nebula-commander/jwt".path;
    debug = false;
  };
}
```

Then build and switch: `nixos-rebuild switch`. The API will be available at `http://127.0.0.1:8081` (bind to 127.0.0.1 by default). Put nginx or another reverse proxy in front for TLS and to serve the frontend.

### Docker

Nebula Commander can be deployed using Docker with NixOS 25.11-based images.

**Quick Start**

```bash
cd docker

# Copy and configure environment
cp .env.example .env
# Edit .env to set JWT_SECRET_KEY and other options

# Build and start services
docker compose up -d

# View logs
docker compose logs -f
```

The application will be available at http://localhost (or the port configured in `.env`).

**Architecture**

- **Frontend container**: Nginx serving the React SPA and proxying `/api` requests
- **Backend container**: FastAPI with Python 3.13, nebula-cert binary, SQLite database

**Configuration**

Edit `docker/.env` to configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `FRONTEND_PORT` | Port for the web UI | `80` |
| `JWT_SECRET_KEY` | Secret for signing JWT tokens | (required) |
| `OIDC_ISSUER_URL` | OIDC provider URL (optional) | — |
| `DEBUG` | Enable debug mode | `false` |

**Data Persistence**

Data is stored in a Docker volume `nebula-commander-data`:

- SQLite database: `/var/lib/nebula-commander/db.sqlite`
- Certificates: `/var/lib/nebula-commander/certs/`

To back up data:

```bash
docker run --rm -v nebula-commander-data:/data -v $(pwd):/backup alpine tar czf /backup/nebula-commander-backup.tar.gz /data
```

**Building Images**

```bash
cd docker

# Build both images
docker compose build

# Build specific image
docker compose build backend
docker compose build frontend
```

### Installing ncclient (device client) from PyPI

The device client is published as the **nebula-commander** package on PyPI. Installing it provides the `ncclient` command:

```bash
pip install nebula-commander
ncclient enroll --server https://YOUR_NEBULA_COMMANDER_URL --code XXXXXXXX
ncclient run --server https://YOUR_NEBULA_COMMANDER_URL
```

See [client/README.md](client/README.md) for full usage (enroll, run, `--nebula`, `--restart-service`, macOS/Windows).

## Configuration

Environment variables (prefix `NEBULA_COMMANDER_` or set in `/etc/nebula-commander/config.env`):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | SQLite (or future PostgreSQL) URL | `sqlite+aiosqlite:///var/lib/nebula-commander/db.sqlite` |
| `CERT_STORE_PATH` | Directory for CA and host certs | `/var/lib/nebula-commander/certs` |
| `PORT` | Backend listen port | `8081` |
| `JWT_SECRET_FILE` | Path to JWT secret (for session/API tokens) | — |
| `OIDC_ISSUER_URL` | OIDC issuer (e.g. Authelia/Authentik). If set, JWTs are validated via JWKS | — |
| `OIDC_CLIENT_ID` | OIDC client ID (used as audience when validating tokens) | — |
| `OIDC_CLIENT_SECRET_FILE` | Path to OIDC client secret (for token exchange if needed) | — |
| `DEBUG` | Enable debug mode (dev token endpoint, verbose logs) | `false` |

## API Reference

Base path: `/api`. All authenticated endpoints require a `Bearer` token (OIDC access token or JWT from dev-token when debug is on).

### Auth

- **GET /api/auth/dev-token** — (Debug only) Return a JWT for development. No auth required.
- **GET /api/auth/me** — Current user info if authenticated.

### Networks

- **GET /api/networks** — List networks.
- **POST /api/networks** — Create network. Body: `{ "name": string, "subnet_cidr": string }`.
- **GET /api/networks/{id}** — Get network by ID.

### Nodes

- **GET /api/nodes** — List nodes. Query: `network_id` (optional).
- **GET /api/nodes/{id}** — Get node by ID.
- **PATCH /api/nodes/{id}** — Update node. Body: `{ "groups"?: string[], "is_lighthouse"?: boolean }`.
- **POST /api/nodes/{id}/heartbeat** — Update node last_seen and set status to active (for monitoring).

### Certificates

- **POST /api/certificates/sign** — Sign a host certificate (betterkeys). Body: `{ "network_id", "name", "public_key", "groups"?, "suggested_ip"?, "duration_days"? }`. Returns `{ "ip_address", "certificate", "ca_certificate" }`.

### Health

- **GET /api** — API name and version.
- **GET /api/health** — Health check.

## Certificate flow

**Sign (betterkeys):** Client generates a keypair locally (`nebula-cert keygen`), sends only the **public key** to Nebula Commander (e.g. via the sign API). Commander allocates an IP, signs the cert, and returns the signed certificate and CA cert. Private key never leaves the client.

**Create (server-generated):** Commander generates the keypair on the server, signs the cert, and stores the private key. The key is returned once in the API response and is also served in the device bundle and node certs zip so enrolled devices get `host.key` without manual copy. Protect `cert_store_path`; it holds private keys for server-created certs.

## Publishing the nebula-commander package to PyPI

The `ncclient` device client is packaged as **nebula-commander** on PyPI.

### One-time setup

1. Create an account at [pypi.org](https://pypi.org/account/register/) (and optionally [test.pypi.org](https://test.pypi.org/account/register/) for testing).
2. Create a PyPI API token: [pypi.org/manage/account/token/](https://pypi.org/manage/account/token/) — scope it to the **nebula-commander** project (or “Entire account” for simplicity). Save the token (e.g. `pypi-...`); you won’t see it again.
3. If the project **nebula-commander** doesn’t exist yet, create it by uploading once (step 4 below) or by adding the name under “Your projects” after the first upload.

### Publish a new version

From the **client/** directory:

1. **Bump version** in [client/pyproject.toml](client/pyproject.toml) — e.g. change `version = "0.1.0"` to `version = "0.1.1"`. PyPI rejects re-uploading the same version.
2. **Build** the package:
   ```bash
   cd client
   pip install build
   python -m build
   ```
   This creates `dist/nebula_commander-<version>-py3-none-any.whl` and a `.tar.gz` source distribution.
3. **Upload to PyPI** (you’ll be prompted for username and password; use `__token__` as username and your API token as password):
   ```bash
   pip install twine
   twine upload dist/*
   ```
   To try **Test PyPI** first: `twine upload --repository testpypi dist/*` (use a Test PyPI token). Install from Test PyPI with: `pip install --index-url https://test.pypi.org/simple/ nebula-commander`.

After a successful upload, users can install with: `pip install nebula-commander`.

## Contributing

Contributions are welcome. Prefer small, focused PRs.

## License

This repository uses multiple licenses by component. See [LICENSE.md](LICENSE.md) for which license applies to which part. In short: backend and frontend are MIT; the client (ncclient) is GPLv3 or later.

## Related Projects

- [Nebula](https://github.com/slackhq/nebula) — Overlay networking
- [NACME](https://github.com/noblepayne/NACME) — ACME for Nebula PKI (design inspiration)
- [defined.net](https://www.defined.net/) — Hosted Nebula management
