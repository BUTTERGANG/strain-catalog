"""WEED application configuration."""
import os
from pathlib import Path
from pydantic_settings import BaseSettings

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    app_name: str = "WEED"
    debug: bool = False
    # Set SECRET_KEY in env for production — stable across restarts, required for signed values
    secret_key: str = os.getenv(
        "SECRET_KEY",
        os.getenv("SESSION_SECRET", "dev-only-insecure-key-change-me"),
    )

    # Database — use Neon postgres if DATABASE_URL is set, else SQLite
    database_url: str = os.getenv(
        "DATABASE_URL",
        f"sqlite+aiosqlite:///{DATA_DIR}/weed.db"
    )
    db_echo: bool = False

    # Port — Replit provides $PORT dynamically
    port: int = int(os.getenv("PORT", "8003"))

    # Replit dev domain for CORS
    replit_dev_domain: str = os.getenv("REPLIT_DEV_DOMAIN", "")

    # Auto-seed
    auto_seed: bool = True

    # Map tiles
    map_tile_url: str = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"

    # Uploads
    upload_dir: str = str(BASE_DIR / "backend" / "uploads")
    max_upload_size_mb: int = 10

    # Session
    session_ttl_hours: int = 24
    secure_cookies: bool = False

    # Rate limiting
    rate_limit_login: str = "20/minute"
    rate_limit_register: str = "10/minute"
    rate_limit_default: str = "120/minute"

    test_mode: bool = False

    # Leafly scraping
    leafly_enabled: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

if settings.database_url.startswith("sqlite"):
    DATA_DIR.mkdir(parents=True, exist_ok=True)