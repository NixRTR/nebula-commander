"""
Application configuration for Nebula Commander
"""
import os
from typing import Optional
from urllib.parse import urlparse

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


def _parse_cors_origins(v: str | list[str]) -> list[str]:
    """Parse CORS_ORIGINS from env: '*' or comma-separated list."""
    if isinstance(v, list):
        return v
    s = (v or "").strip()
    if not s or s == "*":
        return ["*"]
    return [x.strip() for x in s.split(",") if x.strip()]


class Settings(BaseSettings):
    """Application settings"""

    # Application
    app_name: str = "Nebula Commander"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"  # nosec B104 - containerized service, Docker handles network isolation
    port: int = 8081

    # Database (SQLite by default). Use four slashes for absolute path so DB is at /var/lib/... not CWD/var/lib/...
    database_url: str = "sqlite+aiosqlite:////var/lib/nebula-commander/db.sqlite"
    database_path: Optional[str] = None  # Override for SQLite path

    # Certificate store
    cert_store_path: str = "/var/lib/nebula-commander/certs"

    # Encryption at rest (required). Fernet key for encrypting sensitive DB columns and cert store files.
    encryption_key: Optional[str] = None
    encryption_key_file: Optional[str] = None

    # Public URL (app as reached by users: FQDN or host:port, e.g. https://nebula.example.com or http://192.168.1.1:9091)
    # Used to derive OIDC redirect URI and for redirect validation when set
    public_url: Optional[str] = None

    # OIDC
    oidc_issuer_url: Optional[str] = None
    oidc_public_issuer_url: Optional[str] = None  # Public URL for browser redirects (logout, etc.)
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_client_secret_file: Optional[str] = None
    oidc_redirect_uri: Optional[str] = None  # If unset and public_url is set, derived as public_url + /api/auth/callback
    oidc_scopes: str = "openid profile email"

    # JWT (for API / session after OIDC)
    jwt_secret_key: str = "change-this-in-production"
    jwt_secret_file: Optional[str] = None
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60 * 24  # 24 hours

    # Default certificate expiry (days)
    default_cert_expiry_days: int = 365

    # Device token (issued on enroll) expiry in days; long-lived so client can poll
    device_token_expiration_days: int = 3650

    # CORS: env accepts "*" or comma-separated list (avoids JSON parse of env).
    # Set NEBULA_COMMANDER_CORS_ORIGINS in env (e.g. * or frontend URL); no service ports hardcoded.
    cors_origins: str | list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # Session security
    session_https_only: bool = False  # Set to True in production with HTTPS
    
    # Redirect security - allowed hosts for OAuth/OIDC redirects
    # Prevents open redirect vulnerabilities by validating redirect URLs
    allowed_redirect_hosts: str | list[str] = []  # Empty = derive from oidc_redirect_uri
    
    # Email / SMTP
    smtp_enabled: bool = False
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_password_file: Optional[str] = None
    smtp_use_tls: bool = True
    smtp_from_email: str = "noreply@example.com"
    smtp_from_name: str = "Nebula Commander"

    @field_validator("cors_origins", mode="after")
    @classmethod
    def normalize_cors_origins(cls, v: str | list[str]) -> list[str]:
        return _parse_cors_origins(v) if isinstance(v, str) else v
    
    @field_validator("allowed_redirect_hosts", mode="after")
    @classmethod
    def normalize_allowed_redirect_hosts(cls, v: str | list[str]) -> list[str]:
        """Parse allowed redirect hosts from env."""
        if isinstance(v, list):
            return v
        s = (v or "").strip()
        if not s:
            return []
        return [x.strip() for x in s.split(",") if x.strip()]

    @model_validator(mode="after")
    def derive_oidc_redirect_uri_from_public_url(self):
        """When public_url is set: derive oidc_redirect_uri and allowed_redirect_hosts when unset."""
        if not self.public_url:
            return self
        base = self.public_url.rstrip("/")
        if not self.oidc_redirect_uri:
            self.oidc_redirect_uri = f"{base}/api/auth/callback"
        if not self.allowed_redirect_hosts:
            netloc = urlparse(self.public_url).netloc
            if netloc:
                self.allowed_redirect_hosts = [netloc]
        return self

    class Config:
        env_prefix = "NEBULA_COMMANDER_"
        env_file = "/etc/nebula-commander/config.env"
        env_file_encoding = "utf-8"
        case_sensitive = False


def load_jwt_secret(settings_obj: Settings) -> str:
    """Load JWT secret from file if specified."""
    if settings_obj.jwt_secret_file and os.path.exists(settings_obj.jwt_secret_file):
        try:
            with open(settings_obj.jwt_secret_file, "r") as f:
                secret = f.read().strip()
                if secret:
                    return secret
        except Exception as e:
            print(f"Warning: Could not read JWT secret: {e}")
    return settings_obj.jwt_secret_key


def load_oidc_secret(settings_obj: Settings) -> Optional[str]:
    """Load OIDC client secret from file if specified."""
    if settings_obj.oidc_client_secret_file and os.path.exists(
        settings_obj.oidc_client_secret_file
    ):
        try:
            with open(settings_obj.oidc_client_secret_file, "r") as f:
                return f.read().strip()
        except Exception as e:
            print(f"Warning: Could not read OIDC secret: {e}")
    return settings_obj.oidc_client_secret


def load_smtp_password(settings_obj: Settings) -> Optional[str]:
    """Load SMTP password from file if specified."""
    if settings_obj.smtp_password_file and os.path.exists(settings_obj.smtp_password_file):
        try:
            with open(settings_obj.smtp_password_file, "r") as f:
                return f.read().strip()
        except Exception as e:
            print(f"Warning: Could not read SMTP password: {e}")
    return settings_obj.smtp_password


def load_encryption_key(settings_obj: Settings) -> str:
    """Load encryption key from file or env. Required for startup; raises if missing or invalid."""
    key: Optional[str] = None
    if settings_obj.encryption_key_file and os.path.exists(settings_obj.encryption_key_file):
        try:
            with open(settings_obj.encryption_key_file, "r") as f:
                key = f.read().strip()
        except Exception as e:
            raise SystemExit(
                f"NEBULA_COMMANDER_ENCRYPTION_KEY_FILE is set but could not read key: {e}"
            ) from e
    if not key and settings_obj.encryption_key:
        key = settings_obj.encryption_key.strip()
    if not key:
        raise SystemExit(
            "Encryption at rest is required. Set NEBULA_COMMANDER_ENCRYPTION_KEY or "
            "NEBULA_COMMANDER_ENCRYPTION_KEY_FILE (Fernet key). "
            "Generate with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    # Validate key by constructing Fernet
    try:
        from cryptography.fernet import Fernet
        Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as e:
        raise SystemExit(f"Invalid encryption key: {e}") from e
    return key


settings = Settings()
if not getattr(settings, "_jwt_loaded", False):
    settings.jwt_secret_key = load_jwt_secret(settings)
    settings.oidc_client_secret = load_oidc_secret(settings)
    settings.smtp_password = load_smtp_password(settings)
    settings._encryption_key = load_encryption_key(settings)
