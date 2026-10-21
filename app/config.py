"""Application settings, loaded from environment variables (and `.env` for local runs)."""

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SecretStr keeps the password out of reprs and logs.
    database_url: SecretStr

    # Comma-separated list of hostnames the monitor may contact (SSRF allowlist).
    allowed_target_hosts: str = "testtarget"

    monitor_enabled: bool = True
    monitor_tick_seconds: float = Field(1.0, gt=0, le=60)
    monitor_max_workers: int = Field(8, ge=1, le=64)
    http_timeout_seconds: float = Field(5.0, gt=0, le=30)

    failure_threshold: int = Field(2, ge=1, le=10)
    recovery_threshold: int = Field(2, ge=1, le=10)

    log_level: str = "INFO"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset(
            host.strip().lower() for host in self.allowed_target_hosts.split(",") if host.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
