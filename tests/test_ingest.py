import unittest
from importlib.metadata import version
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import cc_logger.ingest as ingest_module
from cc_logger.chat_message import MAX_PLUGIN_BATCH_SIZE, ChatMessage
from cc_logger.config import Config
from cc_logger.runtime import CONFIG_KEY, STATE_KEY
from cc_logger.server import create_app


class TestMessageEndpoint(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.webhook_payloads: list[dict[str, object]] = []
        self.webhook_status = 204

        async def receive_webhook(request: web.Request) -> web.Response:
            self.webhook_payloads.append(await request.json())
            return web.Response(status=self.webhook_status)

        webhook_app = web.Application()
        webhook_app.router.add_post("/webhook", receive_webhook)
        self.webhook_server = TestServer(webhook_app)
        await self.webhook_server.start_server()
        config = Config(
            host="127.0.0.1",
            port=0,
            auth_tokens=(("Alice", "test-token"), ("Bob", "bob-token")),
            discord_webhook_url=str(self.webhook_server.make_url("/webhook")),
            chat_name="IronForged",
            flush_interval_seconds=3600,
        )
        self.app = create_app(config)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.client_closed = False

    async def asyncTearDown(self) -> None:
        if not self.client_closed:
            await self.client.close()
        await self.webhook_server.close()

    def test_rate_limits_unauthorized_request_logs(self) -> None:
        ingest_module._last_unauthorized_log_at = None
        ingest_module._suppressed_unauthorized_requests = 0

        with self.assertLogs("cc_logger.ingest", level="WARNING") as logs:
            ingest_module._log_unauthorized_request("192.0.2.1", 100)
            ingest_module._log_unauthorized_request("192.0.2.1", 101)
            ingest_module._log_unauthorized_request("192.0.2.1", 160)

        self.assertEqual(len(logs.output), 2)
        self.assertIn("suppressed=0", logs.output[0])
        self.assertIn("suppressed=1", logs.output[1])

    async def test_rejects_missing_authorization(self) -> None:
        response = await self.client.post("/messages", json=[])

        self.assertEqual(response.status, 401)

    async def test_rejects_incorrect_authorization(self) -> None:
        with self.assertLogs("cc_logger.ingest", level="WARNING") as logs:
            response = await self.client.post(
                "/messages", headers={"Authorization": "wrong-token"}, json=[]
            )

        self.assertEqual(response.status, 401)
        self.assertIn("remote=127.0.0.1", logs.output[0])

    async def test_sends_online_status_on_startup(self) -> None:
        self.assertEqual(
            self.webhook_payloads,
            [
                {
                    "content": f":green_circle: ONLINE v{version('cc-logger')}",
                    "allowed_mentions": {"parse": []},
                }
            ],
        )

    async def test_logs_startup_configuration(self) -> None:
        client = TestClient(TestServer(create_app(self.app[CONFIG_KEY])))

        try:
            with self.assertLogs("cc_logger.server", level="INFO") as logs:
                await client.start_server()
        finally:
            await client.close()

        output = "\n".join(logs.output)
        self.assertIn(f"Starting CC Logger v{version('cc-logger')}", output)
        self.assertIn("127.0.0.1:0", output)
        self.assertIn("chat=IronForged", output)
        self.assertIn("clients=2", output)
        self.assertIn("flush interval 3600.0s", output)
        self.assertIn("dedupe TTL 600.0s", output)
        self.assertIn("max pending 20000", output)

    async def test_sends_offline_status_on_shutdown(self) -> None:
        await self.client.close()
        self.client_closed = True

        self.assertEqual(
            [payload["content"] for payload in self.webhook_payloads],
            [f":green_circle: ONLINE v{version('cc-logger')}", ":red_circle: OFFLINE"],
        )

    async def test_startup_continues_when_online_status_fails(self) -> None:
        self.webhook_status = 503
        config = Config(
            host="127.0.0.1",
            port=0,
            auth_tokens=(("Alice", "test-token"), ("Bob", "bob-token")),
            discord_webhook_url=str(self.webhook_server.make_url("/webhook")),
            chat_name="IronForged",
            flush_interval_seconds=3600,
        )
        client = TestClient(TestServer(create_app(config)))
        try:
            with self.assertLogs("cc_logger", level="WARNING"):
                await client.start_server()
                response = await client.post("/messages", json=[])
                self.assertEqual(response.status, 401)
            self.webhook_status = 204
        finally:
            await client.close()

    async def test_shutdown_closes_session_when_offline_status_fails(self) -> None:
        state = self.app[STATE_KEY]
        self.webhook_status = 503

        with self.assertLogs("cc_logger", level="WARNING"):
            await self.client.close()
        self.client_closed = True

        self.assertTrue(state.session.closed)

    async def test_shutdown_flushes_pending_messages(self) -> None:
        state = self.app[STATE_KEY]
        state.buffer.add_batch(
            [
                ChatMessage.from_payload(
                    {
                        "id": 1,
                        "timestamp": "2021-01-01T00:00:00Z",
                        "chatType": "CLAN",
                        "chatName": "IronForged",
                        "sender": "Player",
                        "message": "Pending shutdown message",
                    }
                )
            ],
            client_name="Alice",
        )

        await self.client.close()
        self.client_closed = True

        self.assertEqual(state.buffer.pending_count, 0)
        self.assertIn("Pending shutdown message", self.webhook_payloads[-2]["content"])

    async def test_logs_when_shutdown_flush_leaves_messages_undelivered(self) -> None:
        state = self.app[STATE_KEY]
        state.buffer.add_batch(
            [
                ChatMessage.from_payload(
                    {
                        "id": 1,
                        "timestamp": "2021-01-01T00:00:00Z",
                        "chatType": "CLAN",
                        "chatName": "IronForged",
                        "sender": "Player",
                        "message": "Pending shutdown message",
                    }
                )
            ],
            client_name="Alice",
        )
        self.webhook_status = 503

        with self.assertLogs("cc_logger", level="WARNING") as logs:
            await self.client.close()
        self.client_closed = True

        self.assertIn("1 messages will be lost", "\n".join(logs.output))

    async def test_rejects_non_ascii_authorization(self) -> None:
        response = await self.client.post(
            "/messages", headers={"Authorization": "é"}, json=[]
        )

        self.assertEqual(response.status, 401)

    async def test_accepts_valid_message_batch(self) -> None:
        with self.assertLogs("cc_logger.ingest", level="INFO") as logs:
            response = await self.client.post(
                "/messages",
                headers={"Authorization": "test-token"},
                json=[
                    {
                        "id": 123,
                        "timestamp": "2021-01-01T00:00:00Z",
                        "chatType": "CLAN",
                        "chatName": "ironforged",
                        "sender": "Player",
                        "message": "Hello",
                    }
                ],
            )

        self.assertEqual(response.status, 202)
        self.assertEqual(await response.json(), {"accepted": 1})
        self.assertIn("client=Alice", logs.output[0])
        self.assertIn(
            "received=1 buffered=1 merged=0 ignored=0 pending=1", logs.output[0]
        )

    async def test_debug_logs_batch_metadata_without_payload_or_auth_token(
        self,
    ) -> None:
        payload = [
            {
                "id": 789,
                "timestamp": "2021-01-01T00:00:00Z",
                "chatType": "CLAN",
                "chatName": "IronForged",
                "sender": "Player",
                "message": "Compare this raw message",
            }
        ]

        with self.assertLogs("cc_logger.ingest", level="DEBUG") as logs:
            response = await self.client.post(
                "/messages",
                headers={"Authorization": "test-token"},
                json=payload,
            )

        self.assertEqual(response.status, 202)
        self.assertIn("client=Alice", logs.output[0])
        self.assertIn("messages=1", logs.output[0])
        self.assertNotIn("Compare this raw message", "\n".join(logs.output))
        self.assertNotIn("test-token", "\n".join(logs.output))

    async def test_accepts_second_client_token_and_logs_client_name(self) -> None:
        with self.assertLogs("cc_logger.ingest", level="INFO") as logs:
            response = await self.client.post(
                "/messages",
                headers={"Authorization": "bob-token"},
                json=[
                    {
                        "id": 456,
                        "timestamp": "2021-01-01T00:00:00Z",
                        "chatType": "CLAN",
                        "chatName": "IronForged",
                        "sender": "Player",
                        "message": "Hello from Bob",
                    }
                ],
            )

        self.assertEqual(response.status, 202)
        self.assertIn("client=Bob", logs.output[0])
        self.assertNotIn("bob-token", logs.output[0])

    async def test_same_message_id_from_second_client_increases_confidence(
        self,
    ) -> None:
        payload = {
            "id": 123,
            "timestamp": "2021-01-01T00:00:00Z",
            "chatType": "CLAN",
            "chatName": "IronForged",
            "sender": "Player",
            "message": "Shared message",
        }
        first = await self.client.post(
            "/messages", headers={"Authorization": "test-token"}, json=[payload]
        )
        second_payload = {**payload, "id": 456, "timestamp": "2021-01-01T00:00:03Z"}
        with self.assertLogs("cc_logger.ingest", level="INFO") as logs:
            second = await self.client.post(
                "/messages",
                headers={"Authorization": "bob-token"},
                json=[second_payload],
            )

        self.assertEqual(first.status, 202)
        self.assertEqual(second.status, 202)
        self.assertEqual(await first.json(), {"accepted": 1})
        self.assertEqual(await second.json(), {"accepted": 1})
        self.assertIn("buffered=0 merged=1 ignored=0", logs.output[0])
        self.assertEqual(
            self.app[STATE_KEY].buffer.peek_chunk(),
            ("<t:1609459200:t> [2] **Player**: Shared message\n", 1),
        )

    async def test_rejects_invalid_payload(self) -> None:
        with self.assertLogs("cc_logger.ingest", level="WARNING"):
            response = await self.client.post(
                "/messages",
                headers={"Authorization": "test-token"},
                json={"id": 123},
            )

        self.assertEqual(response.status, 400)

    async def test_rejects_invalid_json_and_content_type(self) -> None:
        headers = {"Authorization": "test-token"}
        with self.assertLogs("cc_logger.ingest", level="WARNING"):
            invalid_json = await self.client.post(
                "/messages",
                headers={**headers, "Content-Type": "application/json"},
                data="[",
            )
            invalid_content_type = await self.client.post(
                "/messages", headers=headers, data="[]"
            )

        self.assertEqual(invalid_json.status, 400)
        self.assertEqual(invalid_content_type.status, 400)

    async def test_rejects_non_array_and_oversized_batches(self) -> None:
        headers = {"Authorization": "test-token"}
        with self.assertLogs("cc_logger.ingest", level="WARNING"):
            non_array = await self.client.post("/messages", headers=headers, json={})
            oversized_batch = await self.client.post(
                "/messages", headers=headers, json=[{}] * (MAX_PLUGIN_BATCH_SIZE + 1)
            )

        self.assertEqual(non_array.status, 400)
        self.assertEqual(oversized_batch.status, 400)
        self.assertEqual(self.app[STATE_KEY].buffer.pending_count, 0)

    async def test_accepts_empty_batch(self) -> None:
        response = await self.client.post(
            "/messages", headers={"Authorization": "test-token"}, json=[]
        )

        self.assertEqual(response.status, 202)
        self.assertEqual(await response.json(), {"accepted": 0})

    async def test_returns_service_unavailable_when_buffer_is_full(self) -> None:
        with (
            patch.object(self.app[STATE_KEY].buffer, "add_batch", return_value=None),
            self.assertLogs("cc_logger.ingest", level="WARNING") as logs,
        ):
            response = await self.client.post(
                "/messages",
                headers={"Authorization": "test-token"},
                json=[
                    {
                        "id": 123,
                        "timestamp": "2021-01-01T00:00:00Z",
                        "chatType": "CLAN",
                        "chatName": "IronForged",
                        "sender": "Player",
                        "message": "Hello",
                    }
                ],
            )

        self.assertEqual(response.status, 503)
        self.assertIn("client=Alice", logs.output[0])
        self.assertIn("pending=0/20000 dedupe_ids=0/100000", logs.output[0])

    async def test_rejects_mixed_batch_without_buffering_clan_messages(self) -> None:
        with self.assertLogs("cc_logger.ingest", level="WARNING"):
            response = await self.client.post(
                "/messages",
                headers={"Authorization": "test-token"},
                json=[
                    {
                        "id": 123,
                        "timestamp": "2021-01-01T00:00:00Z",
                        "chatType": "CLAN",
                        "chatName": "IronForged",
                        "sender": "Player",
                        "message": "Clan message",
                    },
                    {
                        "id": 124,
                        "timestamp": "2021-01-01T00:00:01Z",
                        "chatType": "FRIENDS",
                        "chatName": "Friends",
                        "sender": "Player",
                        "message": "Friends message",
                    },
                ],
            )

        self.assertEqual(response.status, 400)
        self.assertEqual(self.app[STATE_KEY].buffer.pending_count, 0)

    async def test_rejects_batch_with_mismatched_chat_name_atomically(self) -> None:
        with self.assertLogs("cc_logger.ingest", level="WARNING") as logs:
            response = await self.client.post(
                "/messages",
                headers={"Authorization": "test-token"},
                json=[
                    {
                        "id": 123,
                        "timestamp": "2021-01-01T00:00:00Z",
                        "chatType": "CLAN",
                        "chatName": "IronForged",
                        "sender": "Player",
                        "message": "Valid clan message",
                    },
                    {
                        "id": 124,
                        "timestamp": "2021-01-01T00:00:01Z",
                        "chatType": "CLAN",
                        "chatName": "OtherClan",
                        "sender": "Player",
                        "message": "Mismatched clan message",
                    },
                ],
            )

        self.assertEqual(response.status, 400)
        self.assertEqual(self.app[STATE_KEY].buffer.pending_count, 0)
        self.assertIn("reason=chat_name_mismatch", logs.output[0])


if __name__ == "__main__":
    unittest.main()
