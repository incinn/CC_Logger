import json
import os
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class Config:
    host: str
    port: int
    auth_tokens: tuple[tuple[str, str], ...]
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
        if not self.auth_tokens:
            raise ValueError("auth_tokens must contain at least one client")
        names: set[str] = set()
        tokens: set[str] = set()
        for name, token in self.auth_tokens:
            if not name.strip():
                raise ValueError("auth token client names must not be empty")
            if not token or token == "none":
                raise ValueError("auth tokens must be configured secrets")
            if name in names:
                raise ValueError("auth token client names must be unique")
            if token in tokens:
                raise ValueError("auth tokens must be unique")
            names.add(name)
            tokens.add(token)
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
        auth_tokens_path = Path(
            os.environ.get("AUTH_TOKENS_FILE", "/run/secrets/auth_tokens.json")
        )
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if not webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL must be set")

        try:
            auth_token_data = json.loads(auth_tokens_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError(
                "AUTH_TOKENS_FILE must point to a readable JSON auth file"
            ) from error
        if not isinstance(auth_token_data, list) or not auth_token_data:
            raise ValueError("AUTH_TOKENS_FILE must contain a non-empty JSON array")

        auth_tokens: list[tuple[str, str]] = []
        for entry in auth_token_data:
            if (
                not isinstance(entry, dict)
                or not isinstance(entry.get("name"), str)
                or not isinstance(entry.get("token"), str)
            ):
                raise ValueError(
                    "AUTH_TOKENS_FILE entries must contain string name and token fields"
                )
            auth_tokens.append((entry["name"], entry["token"]))

        return cls(
            host=os.environ.get("HOST", "0.0.0.0"),
            port=int(os.environ.get("PORT", "8080")),
            auth_tokens=tuple(auth_tokens),
            discord_webhook_url=webhook_url,
            flush_interval_seconds=float(
                os.environ.get("FLUSH_INTERVAL_SECONDS", "30")
            ),
            dedupe_ttl_seconds=float(os.environ.get("DEDUPE_TTL_SECONDS", "600")),
            max_pending_messages=int(os.environ.get("MAX_PENDING_MESSAGES", "20000")),
            max_dedupe_ids=int(os.environ.get("MAX_DEDUPE_IDS", "100000")),
        )
