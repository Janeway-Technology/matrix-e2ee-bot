"""Configuration management via environment variables."""

from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional
import secrets


class Settings(BaseSettings):
    # Matrix server
    matrix_homeserver: str
    matrix_user: str
    matrix_password: Optional[str] = None
    matrix_access_token: Optional[str] = None

    # Bot identity
    bot_display_name: str = "Matrix Bot"
    bot_device_id: Optional[str] = None

    # API security
    api_bearer_token: str = secrets.token_urlsafe(32)

    # Storage
    crypto_store_path: str = "/app/data/crypto_store"
    session_store_path: str = "/app/data/sessions.db"

    # Logging
    log_level: str = "INFO"

    # Sync
    sync_interval: int = 30

    @field_validator("matrix_homeserver")
    @classmethod
    def validate_homeserver(cls, v: str) -> str:
        if not v.startswith(("https://", "http://")):
            raise ValueError("MATRIX_HOMESERVER must start with https:// or http://")
        return v.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return upper

    def validate_auth(self) -> None:
        if not self.matrix_password and not self.matrix_access_token:
            raise ValueError(
                "Either MATRIX_PASSWORD or MATRIX_ACCESS_TOKEN must be set"
            )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
