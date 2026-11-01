import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer

from cc_logger.chat_buffer import ChatBuffer
from cc_logger.chat_message import ChatMessage
from cc_logger.config import Config
from cc_logger.delivery import (
    _parse_retry_after,
    _retry_delay,
    flush_loop,
    flush_pending,
    send_status,
)
from cc_logger.runtime import RuntimeState


def make_payload(
    message_id: int = 1,
    sender: str = "Player",
    chat_name: str = "IronForged",
    message: str = "Hello",
) -> dict[str, object]:
    return {
        "id": message_id,
        "timestamp": "2021-01-01T00:00:00Z",
        "chatType": "CLAN",
        "chatName": chat_name,
        "sender": sender,
        "message": message,
    }


class TestWebhookDelivery(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.webhook_payloads: list[dict[str, object]] = []
        self.webhook_status = 204
        self.webhook_response_statuses: list[int] = []
        self.webhook_headers: dict[str, str] = {}

        async def receive_webhook(request: web.Request) -> web.Response:
            self.webhook_payloads.append(await request.json())
            status = (
                self.webhook_response_statuses.pop(0)
                if self.webhook_response_statuses
                else self.webhook_status
            )
            return web.Response(status=status, headers=self.webhook_headers)

        webhook_app = web.Application()
        webhook_app.router.add_post("/webhook", receive_webhook)
        self.webhook_server = TestServer(webhook_app)
        await self.webhook_server.start_server()
        self.config = Config(
            host="127.0.0.1",
            port=0,
            auth_tokens=(("Alice", "test-token"),),
            discord_webhook_url=str(self.webhook_server.make_url("/webhook")),
        )
        self.buffer = ChatBuffer()
        self.session = ClientSession()
        self.state = RuntimeState(
            config=self.config,
            buffer=self.buffer,
            session=self.session,
            flush_lock=asyncio.Lock(),
        )

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.webhook_server.close()

    def add_message(self, payload: dict[str, object]) -> None:
        self.buffer.add_batch([ChatMessage.from_payload(payload)])

    async def test_flush_posts_discord_lines_and_disables_mentions(self) -> None:
        self.add_message(make_payload())

        with self.assertLogs("cc_logger", level="INFO") as logs:
            result = await flush_pending(self.state)

        self.assertTrue(result.success)
        self.assertIn("Delivered 1 messages to Discord; 0 pending", logs.output[0])
        self.assertEqual(
            self.webhook_payloads,
            [
                {
                    "content": '\u200b\n<t:1609459200:t> **Player** "Hello"\n',
                    "allowed_mentions": {"parse": []},
                }
            ],
        )
        self.assertEqual(self.buffer.pending_count, 0)

    async def test_flush_renders_system_message_as_subtext(self) -> None:
        self.add_message(
            make_payload(sender="Clan", chat_name="Clan", message="Restarting")
        )

        result = await flush_pending(self.state)

        self.assertTrue(result.success)
        self.assertEqual(
            self.webhook_payloads[0]["content"],
            "\u200b\n-# <t:1609459200:t> *Restarting*\n",
        )

    async def test_flush_keeps_messages_after_webhook_failure(self) -> None:
        self.add_message(make_payload())
        self.webhook_status = 503

        with self.assertLogs("cc_logger", level="WARNING"):
            result = await flush_pending(self.state)

        self.assertFalse(result.success)
        self.assertEqual(self.buffer.pending_count, 1)

    async def test_flush_returns_retry_after_for_rate_limited_webhook(self) -> None:
        self.add_message(make_payload())
        self.webhook_status = 429
        self.webhook_headers = {"Retry-After": "5"}

        with self.assertLogs("cc_logger", level="WARNING"):
            result = await flush_pending(self.state)

        self.assertFalse(result.success)
        self.assertEqual(result.retry_after_seconds, 5)
        self.assertEqual(self.buffer.pending_count, 1)

    async def test_status_notification_failure_returns_false(self) -> None:
        self.webhook_status = 503

        with self.assertLogs("cc_logger", level="WARNING"):
            sent = await send_status(self.state, ":green_circle: ONLINE")

        self.assertFalse(sent)

    async def test_status_notification_success_returns_true(self) -> None:
        sent = await send_status(self.state, ":green_circle: ONLINE")

        self.assertTrue(sent)

    async def test_flush_keeps_messages_after_request_timeout(self) -> None:
        self.add_message(make_payload())

        with (
            patch.object(self.session, "post", side_effect=asyncio.TimeoutError),
            self.assertLogs("cc_logger", level="WARNING"),
        ):
            result = await flush_pending(self.state)

        self.assertFalse(result.success)
        self.assertEqual(self.buffer.pending_count, 1)

    async def test_flush_discards_successful_chunk_and_keeps_failed_chunk(self) -> None:
        self.buffer.add_batch(
            [
                ChatMessage.from_payload(
                    make_payload(message_id=1, message="FIRST" + "x" * 1100)
                ),
                ChatMessage.from_payload(
                    make_payload(message_id=2, message="SECOND" + "x" * 1100)
                ),
            ]
        )
        self.webhook_response_statuses = [204, 503]

        with self.assertLogs("cc_logger", level="WARNING"):
            result = await flush_pending(self.state)

        self.assertFalse(result.success)
        self.assertEqual(self.buffer.pending_count, 1)
        self.assertEqual(len(self.webhook_payloads), 2)
        self.assertIn('"FIRST', self.webhook_payloads[0]["content"])
        self.assertIn('"SECOND', self.webhook_payloads[1]["content"])

    def test_parse_retry_after_rejects_invalid_values(self) -> None:
        for value in (None, "invalid", "nan", "inf", "-1"):
            with self.subTest(value=value):
                self.assertIsNone(_parse_retry_after(value))

    def test_parse_retry_after_accepts_zero_and_fractional_seconds(self) -> None:
        self.assertEqual(_parse_retry_after("0"), 0)
        self.assertEqual(_parse_retry_after("1.25"), 1.25)


class TestFlushLoop(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.state = RuntimeState(
            config=Config(
                host="127.0.0.1",
                port=0,
                auth_tokens=(("Alice", "test-token"),),
                discord_webhook_url="https://discord.com/api/webhooks/test",
                flush_interval_seconds=10,
            ),
            buffer=ChatBuffer(),
            session=AsyncMock(),
            flush_lock=asyncio.Lock(),
        )

    async def test_continues_after_unexpected_flush_error(self) -> None:
        sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
        with (
            patch("cc_logger.delivery.asyncio.sleep", sleep),
            patch(
                "cc_logger.delivery.flush_pending",
                new_callable=AsyncMock,
                side_effect=RuntimeError("unexpected"),
            ) as flush,
            self.assertLogs("cc_logger", level="ERROR"),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await flush_loop(self.state)

        flush.assert_awaited_once_with(self.state)

    async def test_uses_retry_after_for_next_flush(self) -> None:
        sleep = AsyncMock(side_effect=[None, None, asyncio.CancelledError()])
        outcomes = [
            SimpleNamespace(success=False, retry_after_seconds=25),
            SimpleNamespace(success=True, retry_after_seconds=None),
        ]
        with (
            self.assertLogs("cc_logger", level="WARNING") as logs,
            patch("cc_logger.delivery.asyncio.sleep", sleep),
            patch("cc_logger.delivery.flush_pending", new_callable=AsyncMock) as flush,
        ):
            flush.side_effect = outcomes
            with self.assertRaises(asyncio.CancelledError):
                await flush_loop(self.state)

        self.assertEqual([call.args[0] for call in sleep.await_args_list], [10, 25, 10])
        self.assertIn("retrying in 25.0 seconds", logs.output[0])
        self.assertIn("attempt 1", logs.output[0])

    async def test_applies_exponential_backoff_with_jitter(self) -> None:
        with patch(
            "cc_logger.delivery.random.uniform",
            side_effect=lambda low, high: (low + high) / 2,
        ):
            delay = _retry_delay(interval=10, failure_count=3)

        self.assertAlmostEqual(delay, 40)

    async def test_backoff_cap_does_not_reduce_configured_interval(self) -> None:
        with patch(
            "cc_logger.delivery.random.uniform",
            side_effect=lambda low, high: (low + high) / 2,
        ):
            delay = _retry_delay(interval=400, failure_count=1)

        self.assertAlmostEqual(delay, 400)

    async def test_backoff_jitter_does_not_exceed_retry_cap(self) -> None:
        with patch(
            "cc_logger.delivery.random.uniform", side_effect=lambda low, high: high
        ):
            delay = _retry_delay(interval=10, failure_count=20)

        self.assertEqual(delay, 300)

    async def test_retry_after_is_a_minimum_for_backoff(self) -> None:
        with patch("cc_logger.delivery.random.uniform", return_value=10):
            delay = _retry_delay(interval=10, failure_count=1, retry_after_seconds=25)

        self.assertEqual(delay, 25)

    async def test_rejects_nonpositive_failure_count(self) -> None:
        for failure_count in (0, -1):
            with self.subTest(failure_count=failure_count):
                with self.assertRaises(ValueError):
                    _retry_delay(interval=10, failure_count=failure_count)


if __name__ == "__main__":
    unittest.main()
