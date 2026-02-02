"""
Application configuration for Nebula Commander
"""
import os
from typing import Optional

from pydantic import field_validator
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
    host: str = "0.0.0.0"
    port: int = 8081

    # Database (SQLite by default). Use four slashes for absolute path so DB is at /var/lib/... not CWD/var/lib/...
    database_url: str = "sqlite+aiosqlite:////var/lib/nebula-commander/db.sqlite"
    database_path: Optional[str] = None  # Override for SQLite path

    # Certificate store
    cert_store_path: str = "/var/lib/nebula-commander/certs"

    # OIDC
    oidc_issuer_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_client_secret_file: Optional[str] = None
    oidc_redirect_uri: Optional[str] = None
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

    # CORS: env accepts "*" or comma-separated list (avoids JSON parse of env)
    cors_origins: str | list[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
    ]

    @field_validator("cors_origins", mode="after")
    @classmethod
    def normalize_cors_origins(cls, v: str | list[str]) -> list[str]:
        return _parse_cors_origins(v) if isinstance(v, str) else v

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


settings = Settings()
if not getattr(settings, "_jwt_loaded", False):
    settings.jwt_secret_key = load_jwt_secret(settings)
    settings.oidc_client_secret = load_oidc_secret(settings)
