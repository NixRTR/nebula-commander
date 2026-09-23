"""
backend.config requires a JWT secret and a Fernet encryption key at import time
(see backend/config.py) - set fixed, obviously-fake values before anything
under backend/ gets imported by test collection, so tests don't need real
secrets and don't depend on a developer's local .env.
"""
import os

os.environ.setdefault(
    "NEBULA_COMMANDER_JWT_SECRET_KEY", "test-only-secret-not-for-real-use-0123456789"
)
os.environ.setdefault(
    "NEBULA_COMMANDER_ENCRYPTION_KEY", "3JHm1AwzZ2VQXWkVjE8ryYzX_Qk3l4sO7eHFhE7oR9o="
)
