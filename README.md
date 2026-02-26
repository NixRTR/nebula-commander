# Nebula Commander

A self-hosted control plane for [Nebula](https://github.com/slackhq/nebula) overlay networks.

## Features

- **Networks & nodes** — Create networks, manage nodes, IP allocation, certificates
- **Web UI** — React dashboard; OIDC (e.g. Keycloak) or dev token
- **Device client (ncclient)** — `pip install nebula-commander` for enroll/run; see [client/README.md](client/README.md)

## Status

Early development. Core APIs and UI are implemented.

## Installation

### Development

```bash
cd nebula-commander
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -r backend/requirements.txt
export NEBULA_COMMANDER_DATABASE_URL="sqlite+aiosqlite:///./backend/db.sqlite"
export NEBULA_COMMANDER_CERT_STORE_PATH="./backend/certs"
# Encryption at rest (required). Generate once: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
export NEBULA_COMMANDER_ENCRYPTION_KEY="your-fernet-key-here"
export DEBUG=true
python -m uvicorn backend.main:app --reload --port 8081
```

```bash
cd frontend && npm install && npm run dev
```

Open http://localhost:5173 (dev token when backend is in debug mode).

### NixOS

Import the module from this repo (or a flake) and enable `services.nebula-commander`. See `nix/module.nix` for options.

### Docker

See [docker/README.md](docker/README.md) for build, env, and deployment.

## Configuration

Env prefix `NEBULA_COMMANDER_`. Key options: `DATABASE_URL`, `CERT_STORE_PATH`, **`ENCRYPTION_KEY`** or **`ENCRYPTION_KEY_FILE`** (required; Fernet key for encryption at rest), `JWT_SECRET_KEY` (or `JWT_SECRET_FILE`), `OIDC_ISSUER_URL`, `OIDC_CLIENT_ID`, `DEBUG`. Generate a key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Full list in [docker/env.d.example/backend](docker/env.d.example/backend).

**Existing deployments** upgrading to encryption at rest must run the one-time migration first: set the same encryption key, then `python -m backend.scripts.migrate_encrypt` (from repo root). See [notes/SECURITY_UPGRADES.md](notes/SECURITY_UPGRADES.md).

## API

Base path `/api`. OpenAPI at `/api/docs` when the backend is running.

## Contributing

Contributions welcome; prefer small, focused PRs.

## License

See [LICENSE.md](LICENSE.md). Backend and frontend: MIT. Client (ncclient): GPLv3 or later.
