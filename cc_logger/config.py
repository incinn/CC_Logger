import os
from dataclasses import dataclass
from math import isfinite
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class Config:
    host: str
    port: int
    authorization_token: str
    discord_webhook_url: str
    flush_interval_seconds: float = 30
    dedupe_ttl_seconds: float = 600
    max_pending_messages: int = 20_000
    max_dedupe_ids: int = 100_000

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("host must not be empty")
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if not self.authorization_token or self.authorization_token == "none":
            raise ValueError("authorization_token must be a configured secret")
        webhook = urlsplit(self.discord_webhook_url)
        if webhook.scheme not in {"http", "https"} or not webhook.netloc:
            raise ValueError("discord_webhook_url must be an HTTP or HTTPS URL")
        if (
            not isfinite(self.flush_interval_seconds)
            or self.flush_interval_seconds <= 0
        ):
            raise ValueError("flush_interval_seconds must be greater than zero")
        if not isfinite(self.dedupe_ttl_seconds) or self.dedupe_ttl_seconds <= 0:
            raise ValueError("dedupe_ttl_seconds must be greater than zero")
        if self.max_pending_messages < 1 or self.max_dedupe_ids < 1:
            raise ValueError("buffer limits must be greater than zero")

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("INGEST_TOKEN", "")
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if not token or token == "none":
            raise ValueError("INGEST_TOKEN must be set to a non-empty secret")
        if not webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL must be set")

        return cls(
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8080")),
            authorization_token=token,
            discord_webhook_url=webhook_url,
            flush_interval_seconds=float(
                os.environ.get("FLUSH_INTERVAL_SECONDS", "30")
            ),
            dedupe_ttl_seconds=float(os.environ.get("DEDUPE_TTL_SECONDS", "600")),
            max_pending_messages=int(os.environ.get("MAX_PENDING_MESSAGES", "20000")),
            max_dedupe_ids=int(os.environ.get("MAX_DEDUPE_IDS", "100000")),
        )
