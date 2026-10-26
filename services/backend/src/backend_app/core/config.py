from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from backend_app.core.error_catalog import CONTRACT_VERSION


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="APP_",
        hide_input_in_errors=True,
    )

    name: str = "Ezcmty"
    env: Literal["local", "test", "staging", "production"] = "local"
    version: str = CONTRACT_VERSION
    database_url: SecretStr = SecretStr("")
    redis_url: SecretStr = SecretStr("")
    session_ttl_seconds: int = Field(default=86_400, ge=60)
    wechat_miniapp_app_id: str = ""
    wechat_miniapp_app_secret: SecretStr = SecretStr("")
    payment_new_orders_enabled: bool = False
    import_storage_root: str = ".dev/imports"
    wechatpay_service_provider_merchant_no: str = ""
    wechatpay_merchant_certificate_serial: str = ""
    wechatpay_merchant_private_key: SecretStr = SecretStr("")
    wechatpay_api_v3_key: SecretStr = SecretStr("")
    wechatpay_verification_keys: dict[str, str] = {}
    wechatpay_encryption_key_id: str = ""
    wechatpay_payment_notify_url: str = ""
    wechatpay_profit_sharing_notify_url: str = ""
    wechatpay_platform_receiver_name: SecretStr = SecretStr("")
    resident_session_idle_seconds: int = Field(default=604_800, ge=60)
    resident_session_absolute_seconds: int = Field(default=2_592_000, ge=60)
    resident_login_limit: int = Field(default=30, ge=1)
    resident_phone_limit: int = Field(default=10, ge=1)
    resident_claim_limit: int = Field(default=30, ge=1)
    resident_rate_window_seconds: int = Field(default=600, ge=60)
    admin_session_idle_seconds: int = Field(default=1800, ge=60)
    admin_session_absolute_seconds: int = Field(default=43_200, ge=60)
    admin_trusted_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    platform_admin_cookie_path: str = "/api/platform"
    property_admin_cookie_path: str = "/api/property"
    admin_login_limit: int = Field(default=5, ge=1)
    admin_login_window_seconds: int = Field(default=900, ge=60)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @model_validator(mode="after")
    def validate_service_urls(self) -> Settings:
        if not self.import_storage_root.strip() or (
            self.env in {"staging", "production"}
            and not Path(self.import_storage_root).is_absolute()
        ):
            raise ValueError(
                "APP_IMPORT_STORAGE_ROOT must be an absolute private persistent directory"
            )
        if self.version != CONTRACT_VERSION:
            raise ValueError("APP_VERSION must match the generated API contract revision")
        if not self.database_url.get_secret_value():
            raise ValueError("APP_DATABASE_URL is required")
        if make_url(self.database_url.get_secret_value()).drivername != "postgresql+psycopg":
            raise ValueError("APP_DATABASE_URL must use postgresql+psycopg")
        if not self.redis_url.get_secret_value():
            raise ValueError("APP_REDIS_URL is required")
        if self.admin_session_absolute_seconds < self.admin_session_idle_seconds:
            raise ValueError("Admin absolute lifetime must cover the idle timeout")
        if self.resident_session_absolute_seconds < self.resident_session_idle_seconds:
            raise ValueError("Resident absolute lifetime must cover the idle timeout")
        from urllib.parse import urlsplit

        for origin in self.admin_trusted_origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.path
                or parsed.query
                or parsed.fragment
                or parsed.username
            ):
                raise ValueError("Admin trusted origins must be exact HTTP origins")
            if self.env == "production" and parsed.scheme != "https":
                raise ValueError("Production admin origins must use HTTPS")
        for path in (self.platform_admin_cookie_path, self.property_admin_cookie_path):
            if not path.startswith("/") or path.startswith("//") or any(c in path for c in "?;#"):
                raise ValueError("Admin cookie paths must be absolute URL paths")
        platform_path = self.platform_admin_cookie_path.rstrip("/")
        property_path = self.property_admin_cookie_path.rstrip("/")
        if platform_path == property_path:
            raise ValueError("Admin cookie paths must be isolated")
        if platform_path.startswith(property_path + "/") or property_path.startswith(
            platform_path + "/"
        ):
            raise ValueError("Admin cookie paths must not overlap")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
