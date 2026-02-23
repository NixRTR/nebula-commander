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

Nebula Commander uses a two-tier configuration approach:

### Infrastructure Settings (`docker/.env`)

Edit `docker/.env` for infrastructure-level settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `FRONTEND_PORT` | Port for the web UI | `80` |
| `BACKEND_PORT` | Port for the API (if exposing directly) | `8081` |
| `KEYCLOAK_PORT` | Port for Keycloak (when using Keycloak) | `8080` |
| `JWT_SECRET_FILE` | Path to JWT secret file (optional, more secure) | — |

### Backend Settings (`docker/env.d/backend`)

Edit `docker/env.d/backend` for all backend-specific settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `NEBULA_COMMANDER_DATABASE_URL` | Database connection URL | `sqlite+aiosqlite:////var/lib/nebula-commander/db.sqlite` |
| `NEBULA_COMMANDER_CERT_STORE_PATH` | Certificate storage path | `/var/lib/nebula-commander/certs` |
| `NEBULA_COMMANDER_JWT_SECRET_KEY` | JWT secret for signing tokens | (required) |
| `NEBULA_COMMANDER_JWT_ALGORITHM` | JWT algorithm | `HS256` |
| `NEBULA_COMMANDER_JWT_EXPIRATION_HOURS` | JWT expiration time | `24` |
| `NEBULA_COMMANDER_PUBLIC_URL` | Public app URL (FQDN or host:port); auth uses this | — |
| `NEBULA_COMMANDER_OIDC_ISSUER_URL` | OIDC internal URL (backend→Keycloak, use container port 8080) | — |
| `NEBULA_COMMANDER_OIDC_PUBLIC_ISSUER_URL` | OIDC public URL (browser; FQDN or host:port) | — |
| `NEBULA_COMMANDER_OIDC_CLIENT_ID` | OIDC client ID | — |
| `NEBULA_COMMANDER_OIDC_CLIENT_SECRET` | OIDC client secret | — |
| `NEBULA_COMMANDER_OIDC_REDIRECT_URI` | OIDC callback (optional; derived from PUBLIC_URL if unset) | — |
| `NEBULA_COMMANDER_CORS_ORIGINS` | Allowed CORS origins (include public URL) | — |
| `NEBULA_COMMANDER_DEBUG` | Enable debug mode | `false` |

**Quick Start:**
```bash
cd docker

# Copy example files
cp .env.example .env
cp -r env.d.example env.d

# Edit configuration
nano env.d/backend  # Set JWT secret and other backend settings
```

## OIDC Authentication with Keycloak

Nebula Commander supports OIDC authentication using Keycloak or other OIDC providers. A pre-configured Keycloak setup is available for easy deployment.

### Running with Keycloak

To run Nebula Commander with Keycloak authentication:

```bash
cd docker

# Copy example environment files (if not already done)
cp -r env.d.example env.d

# Edit the files to set passwords and configuration
# IMPORTANT: Change default passwords in production!
nano env.d/keycloak/keycloak
nano env.d/keycloak/postgresql
nano env.d/backend

# Start both Nebula Commander and Keycloak
docker compose -f docker-compose.yml -f docker-compose-keycloak.yml up -d

# View logs
docker compose -f docker-compose.yml -f docker-compose-keycloak.yml logs -f
```

### Zero-touch Keycloak setup (recommended)

Keycloak can create the **nebula-commander** realm, client, roles, and theme at startup with **no Admin UI steps**.

1. **Set backend OIDC variables** in `env.d/backend` (same file the backend uses):
   - **`NEBULA_COMMANDER_PUBLIC_URL`** — URL where users reach the app (FQDN or host:port), e.g. `https://nebula.example.com` or `http://192.168.1.1:9091`. Redirect URI is derived from this; all auth flows use the public interface (frontend and backend can be on different hosts).
   - `NEBULA_COMMANDER_OIDC_ISSUER_URL=http://keycloak:8080/realms/nebula-commander` (internal; use container port 8080)
   - `NEBULA_COMMANDER_OIDC_PUBLIC_ISSUER_URL` — Keycloak as seen by the browser (FQDN or host:port), e.g. `https://auth.example.com/realms/nebula-commander` or `http://host:8082/realms/nebula-commander`
   - `NEBULA_COMMANDER_OIDC_CLIENT_ID=nebula-commander`
   - `NEBULA_COMMANDER_OIDC_CLIENT_SECRET=<choose a secret>`
   - `NEBULA_COMMANDER_OIDC_REDIRECT_URI` is optional when `NEBULA_COMMANDER_PUBLIC_URL` is set (derived as PUBLIC_URL + `/api/auth/callback`). The realm import uses `NEBULA_COMMANDER_PUBLIC_URL` for web origins and post-logout redirects.

2. **Start Keycloak** with the compose file:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose-keycloak.yml up -d
   ```
   On first start, Keycloak imports the realm from `keycloak-import/nebula-commander-realm.json` (placeholders are filled from `env.d/backend`). The realm uses the **nebula** login/account theme (background + logo) automatically. If the realm already exists, import is skipped.

3. **Create a user** in Keycloak Admin (e.g. `http://localhost:8080`) and assign client roles under the `nebula-commander` client (`system-admin`, `network-owner`, or `user`). No other Keycloak configuration is required.

See [keycloak-import/README.md](keycloak-import/README.md) and [keycloak-theme/README.md](keycloak-theme/README.md) for details.

### Keycloak manual setup (optional)

If you prefer not to use realm import, or need a different realm name, configure Keycloak manually:

1. **Access Keycloak Admin Console**
   - URL: `http://localhost:8080` (or your configured `KEYCLOAK_PORT`)
   - Username: `admin` (from `KC_BOOTSTRAP_ADMIN_USERNAME`)
   - Password: `admin` (from `KC_BOOTSTRAP_ADMIN_PASSWORD` - **change this!**)

2. **Create a Realm** (optional, or use `master`)
   - Click "Create Realm"
   - Name: `nebula-commander`
   - Click "Create"

3. **Create a Client**
   - Go to "Clients" → "Create client"
   - **General Settings:**
     - Client type: `OpenID Connect`
     - Client ID: `nebula-commander`
   - Click "Next"
   - **Capability config:**
     - Client authentication: `ON` (confidential client)
     - Authorization: `OFF`
     - Authentication flow: Enable "Standard flow"
   - Click "Next"
   - **Login settings:**
     - Valid redirect URIs: your public app URL + `/api/auth/callback` (e.g. `https://nebula.example.com/api/auth/callback` or `http://192.168.1.1:9091/api/auth/callback`)
     - Valid post logout redirect URIs: your public app URL + `/*`
     - Web origins: your public app URL (FQDN or host:port)
   - Click "Save"

4. **Get Client Secret**
   - Go to the "Credentials" tab
   - Copy the "Client secret"
   - Update `env.d/backend` with the secret:
     ```bash
     NEBULA_COMMANDER_OIDC_CLIENT_SECRET=your-copied-secret-here
     ```

5. **Configure Client Roles** (for multi-user authorization)
   - Go to the "Roles" tab of your client
   - Click "Create role"
   - Create three client roles:
     - **Role name**: `system-admin`
       - **Description**: Full system administration access
     - **Role name**: `network-owner`
       - **Description**: Can create and manage networks
     - **Role name**: `user`
       - **Description**: Basic user access (default)
   - Click "Save" for each role
   
   **Assigning Roles to Users:**
   - Go to "Users" → Select a user → "Role mapping" tab
   - Click "Assign role"
   - Filter by "Filter by clients" → Select your client (`nebula-commander`)
   - Select the appropriate role(s) and click "Assign"
   
   **Setting Default Role:**
   - Go to "Clients" → Your client → "Client scopes" tab
   - Click on the dedicated scope (e.g., `nebula-commander-dedicated`)
   - Go to "Mappers" tab → "Configure a new mapper"
   - Select "User Client Role"
   - Configure:
     - Name: `client-roles`
     - Client ID: `nebula-commander`
     - Token Claim Name: `resource_access.${client_id}.roles`
     - Add to ID token: ON
     - Add to access token: ON
     - Add to userinfo: ON
   - Click "Save"

6. **Update Backend Configuration**
   - Edit `env.d/backend`:
     ```bash
     # Public URL (FQDN or host:port) — redirect URI is derived from this if unset
     NEBULA_COMMANDER_PUBLIC_URL=https://nebula.example.com
     
     # Internal (backend→Keycloak); use container port 8080
     NEBULA_COMMANDER_OIDC_ISSUER_URL=http://keycloak:8080/realms/nebula-commander
     
     # Keycloak as seen by browser (FQDN or host:port)
     NEBULA_COMMANDER_OIDC_PUBLIC_ISSUER_URL=https://auth.example.com/realms/nebula-commander
     
     NEBULA_COMMANDER_OIDC_CLIENT_ID=nebula-commander
     NEBULA_COMMANDER_OIDC_CLIENT_SECRET=your-client-secret
     ```

7. **Restart Backend**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose-keycloak.yml restart backend
   ```

#### Backend can't reach Keycloak ("All connection attempts failed")

The backend talks to Keycloak from inside the Docker network. Use the **container** port in `NEBULA_COMMANDER_OIDC_ISSUER_URL`, not the host-mapped port:

- **Correct:** `NEBULA_COMMANDER_OIDC_ISSUER_URL=http://keycloak:8080/realms/nebula-commander` (Keycloak listens on 8080 inside the container)
- **Wrong:** `http://keycloak:8082/...` if you only mapped host port 8082→8080; from the backend container, nothing listens on 8082

Use the host port (e.g. 8082) or FQDN only in `NEBULA_COMMANDER_OIDC_PUBLIC_ISSUER_URL` and in `NEBULA_COMMANDER_PUBLIC_URL`, so the browser can reach Keycloak and the app.

### User Roles and Permissions

Nebula Commander implements a comprehensive role-based access control (RBAC) system with three user roles:

#### System Admin (`system-admin`)
- **Capabilities:**
  - Manage all users
  - View all networks (limited data: no certificates or IP addresses)
  - View all nodes (limited data: no IP addresses, certificates, or details)
  - Delete networks and nodes (requires reauthentication)
  - Can request temporary access grants from network owners for full access
- **Use Case:** Platform administrators who need oversight but not direct access to network details

#### Network Owner (`network-owner`)
- **Capabilities:**
  - Create new networks (becomes owner)
  - Manage networks they own
  - Manage nodes in their networks
  - Invite users to networks or specific nodes
  - Manage invited users' access to resources
  - Approve or reject node requests
  - Set default node parameters per network
  - Grant temporary access to system admins
  - Configure auto-approval settings per network
- **Use Case:** Team leads or network administrators managing their own Nebula networks

#### User (`user`)
- **Capabilities:**
  - Access only resources granted by network owners
  - Request new nodes (requires approval unless auto-approved)
  - Request higher access levels
  - Must be invited by a network owner
- **Use Case:** Regular users who need access to specific networks or nodes

#### Permission Features

- **Network-Level Permissions**: Users can be granted access to entire networks with specific capabilities (manage nodes, invite users, manage firewall)
- **Node-Level Permissions**: Users can be granted access to specific nodes with granular permissions (view details, download config, download certificates)
- **Node Request Workflow**: Users request nodes, network owners approve/reject
- **Auto-Approval**: Network owners can enable auto-approval for trusted users
- **Access Grants**: Network owners can grant temporary access to system admins for troubleshooting
- **Reauthentication**: Critical operations (delete network/node) require reauthentication via Keycloak

### Email Configuration (Optional)

Nebula Commander can send email invitations to users. To enable this feature, configure SMTP settings in `env.d/backend`:

#### Gmail Example

```bash
NEBULA_COMMANDER_SMTP_ENABLED=true
NEBULA_COMMANDER_SMTP_HOST=smtp.gmail.com
NEBULA_COMMANDER_SMTP_PORT=587
NEBULA_COMMANDER_SMTP_USERNAME=your-email@gmail.com
NEBULA_COMMANDER_SMTP_PASSWORD=your-app-password  # Use App Password, not regular password
NEBULA_COMMANDER_SMTP_USE_TLS=true
NEBULA_COMMANDER_SMTP_FROM_EMAIL=noreply@yourdomain.com
NEBULA_COMMANDER_SMTP_FROM_NAME=Nebula Commander
```

**Important for Gmail:**
1. Enable 2-factor authentication on your Google account
2. Generate an App Password at https://myaccount.google.com/apppasswords
3. Use the App Password (not your regular Gmail password)

#### Other SMTP Providers

**SendGrid:**
```bash
NEBULA_COMMANDER_SMTP_HOST=smtp.sendgrid.net
NEBULA_COMMANDER_SMTP_PORT=587
NEBULA_COMMANDER_SMTP_USERNAME=apikey
NEBULA_COMMANDER_SMTP_PASSWORD=your-sendgrid-api-key
```

**Mailgun:**
```bash
NEBULA_COMMANDER_SMTP_HOST=smtp.mailgun.org
NEBULA_COMMANDER_SMTP_PORT=587
NEBULA_COMMANDER_SMTP_USERNAME=your-mailgun-smtp-username
NEBULA_COMMANDER_SMTP_PASSWORD=your-mailgun-smtp-password
```

**Office 365:**
```bash
NEBULA_COMMANDER_SMTP_HOST=smtp.office365.com
NEBULA_COMMANDER_SMTP_PORT=587
NEBULA_COMMANDER_SMTP_USERNAME=your-office365-email@company.com
NEBULA_COMMANDER_SMTP_PASSWORD=your-office365-password
```

#### Security Best Practices

1. **Use Secret Files**: For production, store passwords in files:
   ```bash
   NEBULA_COMMANDER_SMTP_PASSWORD_FILE=/run/secrets/smtp-password
   ```

2. **Docker Secrets**: Use Docker secrets for sensitive data:
   ```yaml
   secrets:
     smtp-password:
       file: ./secrets/smtp-password.txt
   ```

3. **Environment Isolation**: Keep `env.d/` in `.gitignore` to prevent credential leaks

#### Testing Email Configuration

For local development, you can use [MailHog](https://github.com/mailhog/MailHog) to test emails without sending real ones:

```bash
# Run MailHog in Docker
docker run -d -p 1025:1025 -p 8025:8025 mailhog/mailhog

# Configure Nebula Commander
NEBULA_COMMANDER_SMTP_ENABLED=true
NEBULA_COMMANDER_SMTP_HOST=localhost  # or host.docker.internal from container
NEBULA_COMMANDER_SMTP_PORT=1025
NEBULA_COMMANDER_SMTP_USE_TLS=false

# View emails at http://localhost:8025
```

#### How It Works

1. Network owner creates an invitation through the UI
2. Invitation is saved to the database
3. Email is sent in the background (non-blocking)
4. User receives email with invitation link
5. User clicks link and accepts invitation
6. NetworkPermission is created, granting access

**Note:** If SMTP is disabled or email fails, the invitation link is still displayed in the UI for manual sharing.

### Keycloak Configuration Files

The Keycloak setup uses environment files for configuration:

- **`env.d/keycloak/keycloak`**: Keycloak server settings (database, admin user, hostname)
- **`env.d/keycloak/postgresql`**: PostgreSQL database settings for Keycloak
- **`env.d/backend`**: Nebula Commander OIDC client configuration

**Note**: Example files are in `env.d.example/`. Copy the entire directory to `env.d/` to get started.

#### Custom login/logout background and logo

To use the same background image as the Nebula Commander login screen on Keycloak’s login and logout pages:

1. **Use the provided theme** (recommended):  
   See [keycloak-theme/README.md](keycloak-theme/README.md). The `keycloak-theme` folder contains a minimal theme that extends Keycloak’s default and sets the background. Copy `nebula-bg.webp` from the frontend (`frontend/public/nebula-bg.webp`) into `keycloak-theme/login/resources/img/`, then mount the theme into the Keycloak container and select the theme in the admin console.

2. **Manual theme steps** (if you prefer to build your own):
   - Create a theme that extends the default (e.g. `parent=keycloak` in `theme.properties`).
   - In the login theme’s CSS (e.g. `login/resources/css/login.css`), add:
     ```css
     body { background-image: url(../img/nebula-bg.webp); background-size: cover; background-position: center; }
     ```
   - Place your background image in `login/resources/img/`.
   - Mount the theme directory into the container at `/opt/keycloak/themes/<your-theme-name>` (see Keycloak docs for your version), or package as a JAR and add to `/opt/keycloak/providers/`.
   - In Keycloak Admin: **Realm** → **Realm settings** → **Themes** → set **Login theme** and **Account theme** (for logout) to your theme name, then save.

### Production Deployment

For production use:

1. **Change Default Passwords**
   - Keycloak admin password (`KC_BOOTSTRAP_ADMIN_PASSWORD`)
   - PostgreSQL password (`POSTGRES_PASSWORD` and `KC_DB_PASSWORD`)
   - OIDC client secret

2. **Use HTTPS**
   - Set `KC_HOSTNAME` to your public domain (e.g., `https://auth.example.com`)
   - Configure TLS certificates or use a reverse proxy
   - Set `KC_PROXY=edge` if behind a reverse proxy
   - Update redirect URIs to use HTTPS

3. **Security Settings**
   - Set `KC_HOSTNAME_STRICT=true`
   - Disable HTTP: Remove or set `KC_HTTP_ENABLED=false`
   - Use `start --optimized` instead of `start-dev` in `docker-compose-keycloak.yml`

4. **Persistent Data**
   - Keycloak database is stored in Docker volume `keycloak-db-data`
   - Backup regularly using standard PostgreSQL backup tools

### Running Without Keycloak

To run without Keycloak (development mode with dev tokens):

```bash
cd docker
docker compose up -d
```

The backend will use the `/api/auth/dev-token` endpoint when OIDC is not configured.

### Using External OIDC Provider

To use an external OIDC provider (Authentik, Auth0, etc.) instead of the bundled Keycloak:

1. Configure your OIDC provider with:
   - Redirect URI: your public app URL + `/api/auth/callback` (e.g. `https://nebula.example.com/api/auth/callback`)
   - Client type: Confidential
   - Grant type: Authorization Code

2. Update `env.d/backend`:
   ```bash
   NEBULA_COMMANDER_PUBLIC_URL=https://nebula.example.com
   NEBULA_COMMANDER_OIDC_ISSUER_URL=https://your-oidc-provider.com
   NEBULA_COMMANDER_OIDC_PUBLIC_ISSUER_URL=https://your-oidc-provider.com
   NEBULA_COMMANDER_OIDC_CLIENT_ID=your-client-id
   NEBULA_COMMANDER_OIDC_CLIENT_SECRET=your-client-secret
   ```
   (Redirect URI is derived from `NEBULA_COMMANDER_PUBLIC_URL` when unset.)

3. Run without Keycloak:
   ```bash
   docker compose up -d
   ```

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
