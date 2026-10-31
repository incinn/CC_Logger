import math
import os
import unittest
from unittest.mock import patch

from cc_logger.config import Config


class TestConfig(unittest.TestCase):
    @patch.dict(
        os.environ,
        {"INGEST_TOKEN": "test-token", "DISCORD_WEBHOOK_URL": "https://example.com"},
        clear=True,
    )
    def test_from_env_uses_defaults(self) -> None:
        config = Config.from_env()

        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 8080)
        self.assertEqual(config.flush_interval_seconds, 30)
        self.assertEqual(config.dedupe_ttl_seconds, 600)
        self.assertEqual(config.max_pending_messages, 20_000)
        self.assertEqual(config.max_dedupe_ids, 100_000)

    @patch.dict(
        os.environ,
        {
            "INGEST_TOKEN": "test-token",
            "DISCORD_WEBHOOK_URL": "http://localhost/webhook",
            "HOST": "127.0.0.1",
            "PORT": "9000",
            "FLUSH_INTERVAL_SECONDS": "12.5",
            "DEDUPE_TTL_SECONDS": "45",
            "MAX_PENDING_MESSAGES": "50",
            "MAX_DEDUPE_IDS": "75",
        },
        clear=True,
    )
    def test_from_env_reads_overrides(self) -> None:
        config = Config.from_env()

        self.assertEqual(config.host, "127.0.0.1")
        self.assertEqual(config.port, 9000)
        self.assertEqual(config.flush_interval_seconds, 12.5)
        self.assertEqual(config.dedupe_ttl_seconds, 45)
        self.assertEqual(config.max_pending_messages, 50)
        self.assertEqual(config.max_dedupe_ids, 75)

    def test_from_env_requires_credentials(self) -> None:
        for environment in (
            {},
            {"INGEST_TOKEN": "test-token"},
            {"DISCORD_WEBHOOK_URL": "https://example.com"},
            {
                "INGEST_TOKEN": "none",
                "DISCORD_WEBHOOK_URL": "https://example.com",
            },
        ):
            with self.subTest(environment=environment):
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaises(ValueError):
                        Config.from_env()

    def test_rejects_invalid_constructor_values(self) -> None:
        valid = {
            "host": "127.0.0.1",
            "port": 8080,
            "authorization_token": "test-token",
            "discord_webhook_url": "https://example.com/webhook",
        }
        invalid_values = (
            {"host": ""},
            {"port": -1},
            {"port": 65536},
            {"authorization_token": "none"},
            {"discord_webhook_url": "file:///tmp/webhook"},
            {"flush_interval_seconds": 0},
            {"flush_interval_seconds": math.inf},
            {"dedupe_ttl_seconds": -1},
            {"max_pending_messages": 0},
            {"max_dedupe_ids": 0},
        )

        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    Config(**(valid | invalid))

    @patch.dict(
        os.environ,
        {
            "INGEST_TOKEN": "test-token",
            "DISCORD_WEBHOOK_URL": "https://example.com",
            "PORT": "not-a-port",
        },
        clear=True,
    )
    def test_from_env_rejects_invalid_numeric_values(self) -> None:
        with self.assertRaises(ValueError):
            Config.from_env()


if __name__ == "__main__":
    unittest.main()
