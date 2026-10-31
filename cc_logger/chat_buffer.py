from collections import deque
import time

from cc_logger.chat_message import (
    DISCORD_MESSAGE_LIMIT,
    WEBHOOK_CONTENT_PREFIX,
    ChatMessage,
)


class ChatBuffer:
    def __init__(
        self,
        *,
        dedupe_ttl_seconds: float = 600,
        max_pending_messages: int = 20_000,
        max_dedupe_ids: int = 100_000,
    ) -> None:
        if dedupe_ttl_seconds <= 0:
            raise ValueError("dedupe_ttl_seconds must be greater than zero")
        if max_pending_messages < 1 or max_dedupe_ids < 1:
            raise ValueError("buffer limits must be greater than zero")

        self._dedupe_ttl_seconds = dedupe_ttl_seconds
        self._max_pending_messages = max_pending_messages
        self._max_dedupe_ids = max_dedupe_ids
        self._pending: deque[str] = deque()
        self._seen: dict[int, float] = {}
        self._expiry: deque[tuple[float, int]] = deque()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def add_batch(
        self, messages: list[ChatMessage], now: float | None = None
    ) -> int | None:
        current_time = time.monotonic() if now is None else now
        self._prune_expired(current_time)

        new_messages: list[ChatMessage] = []
        batch_ids: set[int] = set()
        for message in messages:
            if message.message_id in self._seen or message.message_id in batch_ids:
                continue
            batch_ids.add(message.message_id)
            new_messages.append(message)

        if len(self._pending) + len(new_messages) > self._max_pending_messages:
            return None
        if len(self._seen) + len(new_messages) > self._max_dedupe_ids:
            return None

        for message in new_messages:
            self._pending.append(message.format_discord())
            self._seen[message.message_id] = current_time
            self._expiry.append((current_time, message.message_id))
        return len(new_messages)

    def peek_chunk(
        self, max_chars: int = DISCORD_MESSAGE_LIMIT - len(WEBHOOK_CONTENT_PREFIX)
    ) -> tuple[str, int] | None:
        if max_chars < 1:
            raise ValueError("max_chars must be greater than zero")

        lines: list[str] = []
        total_chars = 0
        for line in self._pending:
            if total_chars + len(line) > max_chars:
                break
            lines.append(line)
            total_chars += len(line)
        if not lines:
            return None
        return "".join(lines), len(lines)

    def discard(self, count: int) -> None:
        if count < 0 or count > len(self._pending):
            raise ValueError("count is outside the pending message range")
        for _ in range(count):
            self._pending.popleft()

    def _prune_expired(self, now: float) -> None:
        cutoff = now - self._dedupe_ttl_seconds
        while self._expiry and self._expiry[0][0] <= cutoff:
            received_at, message_id = self._expiry.popleft()
            if self._seen.get(message_id) == received_at:
                del self._seen[message_id]
