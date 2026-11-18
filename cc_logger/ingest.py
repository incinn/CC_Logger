import hmac
import json
import logging
import time

from aiohttp import web

from cc_logger.chat_message import MAX_PLUGIN_BATCH_SIZE, ChatMessage
from cc_logger.runtime import STATE_KEY

logger = logging.getLogger(__name__)
UNAUTHORIZED_LOG_INTERVAL_SECONDS = 60
_last_unauthorized_log_at: float | None = None
_suppressed_unauthorized_requests = 0


def _log_unauthorized_request(remote: str | None, now: float) -> None:
    global _last_unauthorized_log_at, _suppressed_unauthorized_requests
    if (
        _last_unauthorized_log_at is None
        or now - _last_unauthorized_log_at >= UNAUTHORIZED_LOG_INTERVAL_SECONDS
    ):
        logger.warning(
            "Rejected unauthorized request from remote=%s suppressed=%d",
            remote or "unknown",
            _suppressed_unauthorized_requests,
        )
        _last_unauthorized_log_at = now
        _suppressed_unauthorized_requests = 0
    else:
        _suppressed_unauthorized_requests += 1


async def receive_messages(request: web.Request) -> web.Response:
    request_started = time.monotonic()
    state = request.app[STATE_KEY]
    supplied_token = request.headers.get("Authorization", "")
    supplied_token_bytes = supplied_token.encode("utf-8")
    client_name = None
    for name, token in state.config.auth_tokens:
        if hmac.compare_digest(supplied_token_bytes, token.encode("utf-8")):
            client_name = name
    if client_name is None:
        _log_unauthorized_request(request.remote, request_started)
        return web.json_response({"error": "Unauthorized"}, status=401)

    if request.content_type != "application/json":
        logger.warning(
            "Rejected request from client=%s reason=content_type",
            client_name,
        )
        return web.json_response({"error": "Expected JSON array"}, status=400)
    try:
        payload = await request.json()
    except json.JSONDecodeError, UnicodeDecodeError:
        logger.warning(
            "Rejected request from client=%s reason=invalid_json", client_name
        )
        return web.json_response({"error": "Invalid JSON"}, status=400)

    if not isinstance(payload, list) or len(payload) > MAX_PLUGIN_BATCH_SIZE:
        logger.warning(
            "Rejected request from client=%s reason=batch_shape messages=%s",
            client_name,
            len(payload) if isinstance(payload, list) else "non_array",
        )
        return web.json_response(
            {"error": f"Expected an array of at most {MAX_PLUGIN_BATCH_SIZE} messages"},
            status=400,
        )

    logger.debug("Received batch from client=%s messages=%d", client_name, len(payload))

    try:
        messages = [ChatMessage.from_payload(entry) for entry in payload]
    except ValueError as error:
        logger.warning(
            "Rejected batch from client=%s reason=invalid_message error=%s",
            client_name,
            error,
        )
        return web.json_response({"error": str(error)}, status=400)
    expected_chat_name = state.config.chat_name.casefold()
    if any(message.chat_name.casefold() != expected_chat_name for message in messages):
        logger.warning(
            "Rejected batch from client=%s reason=chat_name_mismatch messages=%d",
            client_name,
            len(messages),
        )
        return web.json_response(
            {"error": "Message chatName does not match configured CHAT_NAME"},
            status=400,
        )

    pending_before = state.buffer.pending_count
    accepted = state.buffer.add_batch(messages, client_name=client_name)
    if accepted is None:
        logger.warning(
            "Rejected batch from client=%s reason=buffer_limit received=%d "
            "pending=%d/%d dedupe_ids=%d/%d",
            client_name,
            len(messages),
            state.buffer.pending_count,
            state.config.max_pending_messages,
            state.buffer.dedupe_count,
            state.config.max_dedupe_ids,
        )
        return web.json_response({"error": "In-memory buffer is full"}, status=503)
    if messages:
        buffered = state.buffer.pending_count - pending_before
        merged = accepted - buffered
        ignored = len(messages) - accepted
        logger.info(
            "Ingested batch from client=%s: received=%d buffered=%d merged=%d "
            "ignored=%d pending=%d duration_ms=%.1f",
            client_name,
            len(messages),
            buffered,
            merged,
            ignored,
            state.buffer.pending_count,
            (time.monotonic() - request_started) * 1000,
        )
    return web.json_response({"accepted": accepted}, status=202)
