from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="APP_",
        hide_input_in_errors=True,
    )

    name: str = "Community Property Platform"
    env: Literal["local", "test", "staging", "production"] = "local"
    version: str = "0.1.0"
    database_url: SecretStr = SecretStr("")
    redis_url: SecretStr = SecretStr("")
    session_ttl_seconds: int = Field(default=86_400, ge=60)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @model_validator(mode="after")
    def validate_service_urls(self) -> "Settings":
        if not self.database_url.get_secret_value():
            raise ValueError("APP_DATABASE_URL is required")
        if not self.redis_url.get_secret_value():
            raise ValueError("APP_REDIS_URL is required")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
