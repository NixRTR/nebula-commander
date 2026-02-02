# Nebula Commander Docker Deployment

Docker images for Nebula Commander backend and frontend.

## Quick Start

### Using Pre-built Images (Recommended)

Pre-built images are automatically published to GitHub Container Registry:

```bash
cd docker

# Copy and configure environment
cp .env.example .env
# Edit .env to set JWT_SECRET_KEY and other options

# Pull and start services
docker compose pull
docker compose up -d

# View logs
docker compose logs -f
```

The application will be available at http://localhost (or the port configured in `.env`).

### Building Locally

```bash
cd docker

# Build images
docker compose build

# Start services
docker compose up -d
```

## Images

### Backend
- **Image**: `ghcr.io/nixrtr/nebula-commander-backend:latest`
- **Base**: Python 3.13-slim
- **Includes**: FastAPI, SQLAlchemy, nebula-cert binary
- **Port**: 8081
- **Platforms**: linux/amd64, linux/arm64

### Frontend
- **Image**: `ghcr.io/nixrtr/nebula-commander-frontend:latest`
- **Base**: nginx:alpine
- **Includes**: React SPA, nginx reverse proxy
- **Port**: 80
- **Platforms**: linux/amd64, linux/arm64

## Architecture

```
┌─────────────────────────────────────────────┐
│  Frontend (Nginx)                           │
│  - Serves React SPA                         │
│  - Proxies /api/* to backend                │
│  Port: 80                                   │
└─────────────────┬───────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│  Backend (FastAPI)                          │
│  - REST API                                 │
│  - Certificate management                   │
│  - Database (SQLite)                        │
│  Port: 8081                                 │
└─────────────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────┐
│  Persistent Volume                          │
│  - SQLite database                          │
│  - Nebula certificates                      │
│  Path: /var/lib/nebula-commander            │
└─────────────────────────────────────────────┘
```

## Configuration

Edit `docker/.env` to configure:

| Variable | Description | Default |
|----------|-------------|---------|
| `FRONTEND_PORT` | Port for the web UI | `80` |
| `BACKEND_PORT` | Port for the API (if exposing directly) | `8081` |
| `JWT_SECRET_KEY` | Secret for signing JWT tokens | (required) |
| `OIDC_ISSUER_URL` | OIDC provider URL (optional) | — |
| `OIDC_CLIENT_ID` | OIDC client ID | `nebula-commander` |
| `DEBUG` | Enable debug mode | `false` |

## Data Persistence

Data is stored in a Docker volume `nebula-commander-data`:

- SQLite database: `/var/lib/nebula-commander/db.sqlite`
- Certificates: `/var/lib/nebula-commander/certs/`

### Backup Data

```bash
docker run --rm \
  -v nebula-commander-data:/data \
  -v $(pwd):/backup \
  alpine tar czf /backup/nebula-commander-backup.tar.gz /data
```

### Restore Data

```bash
docker run --rm \
  -v nebula-commander-data:/data \
  -v $(pwd):/backup \
  alpine tar xzf /backup/nebula-commander-backup.tar.gz -C /
```

## Image Tags

Images are automatically built and tagged by GitHub Actions:

### Version Tags (on release)
- `v1.2.3` → `ghcr.io/nixrtr/nebula-commander-backend:1.2.3`
- `v1.2.3` → `ghcr.io/nixrtr/nebula-commander-backend:1.2`
- `v1.2.3` → `ghcr.io/nixrtr/nebula-commander-backend:1`
- `v1.2.3` → `ghcr.io/nixrtr/nebula-commander-backend:latest`

## Pulling Images

Images are public and can be pulled without authentication:

```bash
# Latest version
docker pull ghcr.io/nixrtr/nebula-commander-backend:latest
docker pull ghcr.io/nixrtr/nebula-commander-frontend:latest

# Specific version
docker pull ghcr.io/nixrtr/nebula-commander-backend:1.2.3
docker pull ghcr.io/nixrtr/nebula-commander-frontend:1.2.3
```

## Multi-Architecture Support

Images are built for multiple architectures:
- **linux/amd64**: Intel/AMD x86_64 (standard servers, desktops)
- **linux/arm64**: ARM64/aarch64 (Raspberry Pi 4/5, AWS Graviton, Apple Silicon with Docker)

Docker automatically pulls the correct architecture for your platform.

## Building Images

### Local Build

```bash
cd docker
docker compose build
```

### Multi-Architecture Build

Requires Docker Buildx:

```bash
# Backend
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/backend/Dockerfile \
  -t ghcr.io/nixrtr/nebula-commander-backend:latest \
  --push \
  .

# Frontend
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/frontend/Dockerfile \
  -t ghcr.io/nixrtr/nebula-commander-frontend:latest \
  --push \
  .
```

## GitHub Actions

Images are automatically built and pushed by GitHub Actions:

- **Workflow**: `.github/workflows/build-docker-images.yml`
- **Triggers**:
  - Version tags (`v*`) → Build and push with version tags
  - Manual trigger → Build and push

### Workflow Features

- ✅ Multi-architecture builds (amd64, arm64)
- ✅ Layer caching for faster builds
- ✅ Automatic tagging (version, latest, branch, PR)
- ✅ Parallel builds (backend and frontend)
- ✅ Push to GitHub Container Registry

## Troubleshooting

### Images Not Pulling

If you get permission errors, the images might be private. Make sure they're set to public in GitHub:
1. Go to https://github.com/orgs/NixRTR/packages
2. Find the package
3. Click "Package settings"
4. Change visibility to "Public"

### Data Not Persisting

Make sure you're using the named volume `nebula-commander-data` and not overriding paths:
- ✅ Use default paths in docker-compose.yml
- ❌ Don't override `NEBULA_COMMANDER_DATABASE_URL` to paths outside `/var/lib/nebula-commander`

### Backend Health Check Failing

Check backend logs:
```bash
docker compose logs backend
```

Common issues:
- Database path not writable
- Port already in use
- Missing JWT secret

### Frontend Not Loading

Check frontend logs:
```bash
docker compose logs frontend
```

Make sure backend is healthy:
```bash
docker compose ps
```

## Development

### Hot Reload (Backend)

For development with hot reload:

```bash
# Run backend with volume mount
docker run -it --rm \
  -v $(pwd):/app \
  -p 8081:8081 \
  -e DEBUG=true \
  ghcr.io/nixrtr/nebula-commander-backend:latest \
  uvicorn backend.main:app --reload --host 0.0.0.0 --port 8081
```

### Frontend Development

For frontend development, use the local dev server instead of Docker:

```bash
cd frontend
npm install
npm run dev
```

## Production Deployment

### Reverse Proxy

Put a reverse proxy (nginx, Traefik, Caddy) in front for:
- TLS/HTTPS
- Custom domain
- Rate limiting
- Access logs

Example nginx config:

```nginx
server {
    listen 443 ssl http2;
    server_name nebula.example.com;

    ssl_certificate /etc/ssl/certs/nebula.example.com.crt;
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

### Security

- ✅ Use a strong `JWT_SECRET_KEY` (32+ random characters)
- ✅ Enable OIDC authentication for production
- ✅ Use HTTPS (reverse proxy with TLS)
- ✅ Restrict CORS origins (set `CORS_ORIGINS` to your domain)
- ✅ Keep images updated (rebuild regularly)
- ✅ Back up data regularly

### Monitoring

Add health checks to your monitoring system:

```bash
# Backend health
curl http://localhost:8081/api/health

# Frontend health
curl http://localhost/health
```

## Support

- Documentation: https://github.com/NixRTR/nebula-commander
- Issues: https://github.com/NixRTR/nebula-commander/issues
- Docker Hub: https://github.com/orgs/NixRTR/packages
