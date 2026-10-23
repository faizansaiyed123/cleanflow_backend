"""
Central application configuration.
All environment-driven values live here so the rest of the app never reads
os.environ directly. This keeps configuration auditable in one place.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "CleanFlow"
    environment: str = "development"

    # Database
    database_url: str = "sqlite:///./cleanflow.db"

    # Auth
    jwt_secret_key: str = "dev-secret-change-in-production-please"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12  # 12 hours

    # File storage (local disk for the demo; swap for S3-compatible storage
    # in production by replacing app/uploads/storage.py only)
    upload_root: str = "./storage/uploads"
    max_upload_size_mb: int = 8
    allowed_image_types: tuple = ("image/jpeg", "image/png", "image/webp")

    # Business defaults
    default_currency: str = "USD"
    default_tax_rate_percent: float = 0.0
    quote_default_validity_days: int = 14

    cors_origins: list = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # Set true in the test suite so APScheduler's real timers never run
    # concurrently with test assertions -- tests call the worker's job
    # functions directly and synchronously instead (see tests/test_events_and_webhooks.py).
    disable_background_worker: bool = False

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()
