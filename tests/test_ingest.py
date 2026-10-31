import unittest
from importlib.metadata import version
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from cc_logger.chat_message import MAX_PLUGIN_BATCH_SIZE, ChatMessage
from cc_logger.config import Config
from cc_logger.runtime import STATE_KEY
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
            authorization_token="test-token",
            discord_webhook_url=str(self.webhook_server.make_url("/webhook")),
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

    async def test_rejects_missing_authorization(self) -> None:
        response = await self.client.post("/messages", json=[])

        self.assertEqual(response.status, 401)

    async def test_rejects_incorrect_authorization(self) -> None:
        response = await self.client.post(
            "/messages", headers={"Authorization": "wrong-token"}, json=[]
        )

        self.assertEqual(response.status, 401)

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
            authorization_token="test-token",
            discord_webhook_url=str(self.webhook_server.make_url("/webhook")),
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
            ]
        )

        await self.client.close()
        self.client_closed = True

        self.assertEqual(state.buffer.pending_count, 0)
        self.assertIn("Pending shutdown message", self.webhook_payloads[-2]["content"])

    async def test_rejects_non_ascii_authorization(self) -> None:
        response = await self.client.post(
            "/messages", headers={"Authorization": "é"}, json=[]
        )

        self.assertEqual(response.status, 401)

    async def test_accepts_valid_message_batch(self) -> None:
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

        self.assertEqual(response.status, 202)
        self.assertEqual(await response.json(), {"accepted": 1})

    async def test_rejects_invalid_payload(self) -> None:
        response = await self.client.post(
            "/messages",
            headers={"Authorization": "test-token"},
            json={"id": 123},
        )

        self.assertEqual(response.status, 400)

    async def test_rejects_invalid_json_and_content_type(self) -> None:
        headers = {"Authorization": "test-token"}
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
        with patch.object(self.app[STATE_KEY].buffer, "add_batch", return_value=None):
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

    async def test_rejects_mixed_batch_without_buffering_clan_messages(self) -> None:
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


if __name__ == "__main__":
    unittest.main()
