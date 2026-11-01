import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cc_logger.config import Config


class TestConfig(unittest.TestCase):
    def test_from_env_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth_tokens_path = Path(directory) / "auth_tokens.json"
            auth_tokens_path.write_text(
                json.dumps(
                    [
                        {"name": "Alice", "token": "test-token"},
                        {"name": "Bob", "token": "bob-token"},
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "AUTH_TOKENS_FILE": str(auth_tokens_path),
                    "DISCORD_WEBHOOK_URL": "https://example.com",
                },
                clear=True,
            ):
                config = Config.from_env()

        self.assertEqual(config.host, "0.0.0.0")
        self.assertEqual(config.port, 8080)
        self.assertEqual(
            config.auth_tokens,
            (("Alice", "test-token"), ("Bob", "bob-token")),
        )
        self.assertEqual(config.flush_interval_seconds, 30)
        self.assertEqual(config.dedupe_ttl_seconds, 600)
        self.assertEqual(config.max_pending_messages, 20_000)
        self.assertEqual(config.max_dedupe_ids, 100_000)

    def test_from_env_reads_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth_tokens_path = Path(directory) / "auth_tokens.json"
            auth_tokens_path.write_text(
                json.dumps([{"name": "Alice", "token": "test-token"}]),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "AUTH_TOKENS_FILE": str(auth_tokens_path),
                    "DISCORD_WEBHOOK_URL": "http://localhost/webhook",
                    "HOST": "127.0.0.1",
                    "PORT": "9000",
                    "FLUSH_INTERVAL_SECONDS": "12.5",
                    "DEDUPE_TTL_SECONDS": "45",
                    "MAX_PENDING_MESSAGES": "50",
                    "MAX_DEDUPE_IDS": "75",
                },
                clear=True,
            ):
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
            {"AUTH_TOKENS_FILE": "missing.json"},
            {"DISCORD_WEBHOOK_URL": "https://example.com"},
            {
                "AUTH_TOKENS_FILE": "missing.json",
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
            "auth_tokens": (("Alice", "test-token"),),
            "discord_webhook_url": "https://example.com/webhook",
        }
        invalid_values = (
            {"host": ""},
            {"port": -1},
            {"port": 65536},
            {"auth_tokens": ()},
            {"auth_tokens": (("", "test-token"),)},
            {"auth_tokens": (("Alice", "none"),)},
            {"auth_tokens": (("Alice", "token"), ("Alice", "other-token"))},
            {"auth_tokens": (("Alice", "token"), ("Bob", "token"))},
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

    def test_from_env_rejects_invalid_numeric_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth_tokens_path = Path(directory) / "auth_tokens.json"
            auth_tokens_path.write_text(
                json.dumps([{"name": "Alice", "token": "test-token"}]),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "AUTH_TOKENS_FILE": str(auth_tokens_path),
                    "DISCORD_WEBHOOK_URL": "https://example.com",
                    "PORT": "not-a-port",
                },
                clear=True,
            ):
                with self.assertRaises(ValueError):
                    Config.from_env()

    def test_from_env_rejects_malformed_auth_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth_tokens_path = Path(directory) / "auth_tokens.json"
            for auth_file_contents in (
                "{",
                "{}",
                "[]",
                '[{"name":"Alice","token":null}]',
            ):
                with self.subTest(auth_file_contents=auth_file_contents):
                    auth_tokens_path.write_text(auth_file_contents, encoding="utf-8")
                    with patch.dict(
                        os.environ,
                        {
                            "AUTH_TOKENS_FILE": str(auth_tokens_path),
                            "DISCORD_WEBHOOK_URL": "https://example.com",
                        },
                        clear=True,
                    ):
                        with self.assertRaises(ValueError):
                            Config.from_env()

    def test_from_env_rejects_duplicate_auth_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            auth_tokens_path = Path(directory) / "auth_tokens.json"
            auth_tokens_path.write_text(
                json.dumps(
                    [
                        {"name": "Alice", "token": "same-token"},
                        {"name": "Bob", "token": "same-token"},
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "AUTH_TOKENS_FILE": str(auth_tokens_path),
                    "DISCORD_WEBHOOK_URL": "https://example.com",
                },
                clear=True,
            ):
                with self.assertRaises(ValueError):
                    Config.from_env()


if __name__ == "__main__":
    unittest.main()
