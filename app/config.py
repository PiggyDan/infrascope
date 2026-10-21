"""Application settings, loaded from environment variables (and `.env` for local runs)."""

import ipaddress
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

# An explicitly allowlisted range must be at least this specific, so a typo like
# "0.0.0.0/0" can never open the monitor up to the whole internet or LAN.
MIN_PREFIX = {4: 16, 6: 48}


def parse_networks(raw: str) -> tuple[IPNetwork, ...]:
    networks = []
    for item in (part.strip() for part in raw.split(",")):
        if not item:
            continue
        network = ipaddress.ip_network(item, strict=False)
        if network.prefixlen < MIN_PREFIX[network.version]:
            raise ValueError(
                f"{item}: too broad; allowlist specific hosts or ranges "
                f"(IPv{network.version} prefix must be /{MIN_PREFIX[network.version]} or longer)"
            )
        networks.append(network)
    return tuple(networks)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # SecretStr keeps the password out of reprs and logs.
    database_url: SecretStr

    # SSRF allowlists. Hostnames the monitor (and webhooks) may contact, comma-separated.
    allowed_target_hosts: str = "testtarget"
    # Optional explicit opt-in for IP-literal destinations, e.g. "10.20.0.15/32,10.20.1.0/24".
    # Loopback, link-local (incl. cloud metadata), multicast and unspecified addresses stay
    # blocked even inside these ranges.
    allowed_target_networks: str = ""

    monitor_enabled: bool = True
    monitor_tick_seconds: float = Field(1.0, gt=0, le=60)
    monitor_max_workers: int = Field(8, ge=1, le=64)
    http_timeout_seconds: float = Field(5.0, gt=0, le=30)

    failure_threshold: int = Field(2, ge=1, le=10)
    recovery_threshold: int = Field(2, ge=1, le=10)

    # Incident webhooks (disabled when no URL is set).
    notify_webhook_url: str | None = None
    notify_webhook_secret: SecretStr | None = None
    notify_timeout_seconds: float = Field(5.0, gt=0, le=30)
    notify_max_attempts: int = Field(8, ge=1, le=20)

    log_level: str = "INFO"

    @field_validator("allowed_target_networks")
    @classmethod
    def _validate_networks(cls, value: str) -> str:
        parse_networks(value)
        return value

    @field_validator("notify_webhook_url")
    @classmethod
    def _blank_url_means_disabled(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None

    @field_validator("notify_webhook_secret", mode="before")
    @classmethod
    def _blank_secret_means_unsigned(cls, value):
        # Compose passes unset variables as "", which must not count as a signing key.
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset(
            host.strip().lower() for host in self.allowed_target_hosts.split(",") if host.strip()
        )

    @property
    def allowed_networks(self) -> tuple[IPNetwork, ...]:
        return parse_networks(self.allowed_target_networks)

    @property
    def notifications_enabled(self) -> bool:
        return self.notify_webhook_url is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
