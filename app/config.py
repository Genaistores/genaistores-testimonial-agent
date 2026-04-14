from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    grok_api_key: str | None = Field(default=None, validation_alias=AliasChoices("GROK_API_KEY", "XAI_API_KEY"))
    xai_base_url: str = "https://api.x.ai/v1"
    grok_model: str = Field(default="grok-beta", validation_alias=AliasChoices("GROK_MODEL", "XAI_MODEL"))

    gumroad_access_token: str | None = None
    gumroad_product_permalink: str | None = None
    gumroad_webhook_secret: str | None = None

    db_url: str = Field(default="sqlite+aiosqlite:///./app.db", validation_alias=AliasChoices("DB_URL", "DATABASE_URL"))
    default_daily_limit: int = 10

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from_email: str | None = None
    smtp_use_starttls: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
