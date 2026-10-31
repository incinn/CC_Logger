import hmac
import json
import logging

from aiohttp import web

from cc_logger.chat_message import MAX_PLUGIN_BATCH_SIZE, ChatMessage
from cc_logger.runtime import STATE_KEY

logger = logging.getLogger(__name__)


async def receive_messages(request: web.Request) -> web.Response:
    state = request.app[STATE_KEY]
    supplied_token = request.headers.get("Authorization", "")
    if not hmac.compare_digest(
        supplied_token.encode("utf-8"), state.config.authorization_token.encode("utf-8")
    ):
        return web.json_response({"error": "Unauthorized"}, status=401)

    if request.content_type != "application/json":
        return web.json_response({"error": "Expected JSON array"}, status=400)
    try:
        payload = await request.json()
    except json.JSONDecodeError, UnicodeDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    if not isinstance(payload, list) or len(payload) > MAX_PLUGIN_BATCH_SIZE:
        return web.json_response(
            {"error": f"Expected an array of at most {MAX_PLUGIN_BATCH_SIZE} messages"},
            status=400,
        )

    try:
        messages = [ChatMessage.from_payload(entry) for entry in payload]
    except ValueError as error:
        return web.json_response({"error": str(error)}, status=400)

    accepted = state.buffer.add_batch(messages)
    if accepted is None:
        logger.warning(
            "Rejected batch of %d messages; buffer full at %d pending",
            len(messages),
            state.buffer.pending_count,
        )
        return web.json_response({"error": "In-memory buffer is full"}, status=503)
    if messages:
        logger.info(
            "Ingested batch: received=%d new=%d duplicates=%d pending=%d",
            len(messages),
            accepted,
            len(messages) - accepted,
            state.buffer.pending_count,
        )
    return web.json_response({"accepted": accepted}, status=202)
