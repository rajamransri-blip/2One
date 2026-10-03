"""Configuration: production refuses ephemeral secrets and unprotected HTTP."""
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./child_safety.db"))
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET", ""))
    app_env: str = field(default_factory=lambda: os.getenv("APP_ENV", "local"))
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_anon_key: str = field(default_factory=lambda: os.getenv("SUPABASE_ANON_KEY", ""))
    media_dir: str = field(default_factory=lambda: os.getenv("MEDIA_DIR", "./private_media"))
    max_connections: int = field(default_factory=lambda: int(os.getenv("MAX_WS_CONNECTIONS", "200")))
    retention_days: int = field(default_factory=lambda: int(os.getenv("LOCATION_RETENTION_DAYS", "30")))
    online_seconds: int = field(default_factory=lambda: int(os.getenv("ONLINE_SECONDS", "180")))
    pair_minutes: int = field(default_factory=lambda: int(os.getenv("PAIR_CODE_MINUTES", "10")))
    request_limit: int = field(default_factory=lambda: int(os.getenv("REQUESTS_PER_MINUTE", "120")))

    def __post_init__(self):
        if self.app_env == "production" and (len(self.jwt_secret) < 32 or self.database_url.startswith("sqlite")):
            raise ValueError("Production requires a 32+ character JWT_SECRET and PostgreSQL DATABASE_URL")
        if self.app_env == "production" and not (self.supabase_url and self.supabase_anon_key):
            raise ValueError("Production requires Supabase Auth configuration")
        if bool(self.supabase_url) != bool(self.supabase_anon_key):
            raise ValueError("Set both SUPABASE_URL and SUPABASE_ANON_KEY or neither")
        if not self.jwt_secret:
            self.jwt_secret = secrets.token_urlsafe(48)  # local-only; tokens expire across restarts
        if self.max_connections < 1 or not 1 <= self.retention_days <= 365 or self.request_limit < 1:
            raise ValueError("Invalid resource limits")
        Path(self.media_dir).mkdir(parents=True, exist_ok=True)
