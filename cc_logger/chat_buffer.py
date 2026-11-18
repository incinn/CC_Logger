from collections import deque
from dataclasses import dataclass
import hashlib
import json
import time
import unicodedata

from cc_logger.chat_message import (
    DISCORD_MESSAGE_LIMIT,
    WEBHOOK_CONTENT_PREFIX,
    ChatMessage,
)

MESSAGE_TIMESTAMP_TOLERANCE_SECONDS = 5


@dataclass(slots=True, eq=False)
class _BufferedMessage:
    message: ChatMessage
    received_at: float
    fingerprint: str
    clients: set[str]
    delivered: bool = False

    def format_discord(self) -> str:
        return self.message.format_discord(confidence=len(self.clients))


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
        self._pending: deque[_BufferedMessage] = deque()
        self._seen: dict[str, list[_BufferedMessage]] = {}
        self._seen_by_message_id: dict[int, list[_BufferedMessage]] = {}
        self._seen_count = 0
        self._expiry: deque[tuple[float, _BufferedMessage]] = deque()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def add_batch(
        self,
        messages: list[ChatMessage],
        *,
        client_name: str,
        now: float | None = None,
    ) -> int | None:
        current_time = time.monotonic() if now is None else now
        self._prune_expired(current_time)

        normalized_client_name = client_name.casefold()
        new_records: list[_BufferedMessage] = []
        new_records_by_fingerprint: dict[str, list[_BufferedMessage]] = {}
        new_records_by_message_id: dict[int, list[_BufferedMessage]] = {}
        planned_clients: dict[_BufferedMessage, set[str]] = {}
        accepted = 0

        for message in messages:
            fingerprint = self._fingerprint(message)
            message_id_candidates = (
                self._seen_by_message_id.get(message.message_id, [])
                + new_records_by_message_id.get(message.message_id, [])
                if message.message_id
                else []
            )
            matching_records = [
                record
                for record in message_id_candidates
                if record.fingerprint == fingerprint
            ]

            if not matching_records:
                fingerprint_candidates = self._seen.get(
                    fingerprint, []
                ) + new_records_by_fingerprint.get(fingerprint, [])
                matching_records = [
                    record
                    for record in fingerprint_candidates
                    if normalized_client_name
                    not in planned_clients.get(record, record.clients)
                    and abs(record.message.timestamp - message.timestamp)
                    <= MESSAGE_TIMESTAMP_TOLERANCE_SECONDS
                ]

            if matching_records:
                buffered_message = min(
                    matching_records,
                    key=lambda record: abs(
                        record.message.timestamp - message.timestamp
                    ),
                )
                if buffered_message.delivered:
                    continue

                clients = planned_clients.get(
                    buffered_message, buffered_message.clients
                )
                if normalized_client_name not in clients:
                    updated_clients = set(clients)
                    updated_clients.add(normalized_client_name)
                    planned_clients[buffered_message] = updated_clients
                    accepted += 1
                continue

            buffered_message = _BufferedMessage(
                message,
                current_time,
                fingerprint,
                {normalized_client_name},
            )
            new_records.append(buffered_message)
            new_records_by_fingerprint.setdefault(fingerprint, []).append(
                buffered_message
            )
            if message.message_id:
                new_records_by_message_id.setdefault(message.message_id, []).append(
                    buffered_message
                )
            accepted += 1

        if len(self._pending) + len(new_records) > self._max_pending_messages:
            return None
        if self._seen_count + len(new_records) > self._max_dedupe_ids:
            return None

        for buffered_message, clients in planned_clients.items():
            buffered_message.clients = clients
        for buffered_message in new_records:
            self._seen.setdefault(buffered_message.fingerprint, []).append(
                buffered_message
            )
            if buffered_message.message.message_id:
                self._seen_by_message_id.setdefault(
                    buffered_message.message.message_id, []
                ).append(buffered_message)
            self._expiry.append((current_time, buffered_message))
            self._pending.append(buffered_message)
        self._seen_count += len(new_records)
        return accepted

    @staticmethod
    def _fingerprint(message: ChatMessage) -> str:
        sender = unicodedata.normalize("NFC", message.sender).casefold()
        sender = unicodedata.normalize("NFC", sender)
        normalized_message = unicodedata.normalize(
            "NFC", message.message.replace("\r\n", "\n").replace("\r", "\n")
        )
        identity = json.dumps(
            [sender, normalized_message],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def peek_chunk(
        self, max_chars: int = DISCORD_MESSAGE_LIMIT - len(WEBHOOK_CONTENT_PREFIX)
    ) -> tuple[str, int] | None:
        if max_chars < 1:
            raise ValueError("max_chars must be greater than zero")

        lines: list[str] = []
        total_chars = 0
        for message in self._pending:
            line = message.format_discord()
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
            self._pending.popleft().delivered = True

    def _prune_expired(self, now: float) -> None:
        cutoff = now - self._dedupe_ttl_seconds
        while self._expiry and self._expiry[0][0] <= cutoff:
            received_at, buffered_message = self._expiry.popleft()
            fingerprint_records = self._seen.get(buffered_message.fingerprint)
            if (
                fingerprint_records is not None
                and buffered_message.received_at == received_at
            ):
                fingerprint_records.remove(buffered_message)
                if not fingerprint_records:
                    del self._seen[buffered_message.fingerprint]
                if buffered_message.message.message_id:
                    message_id_records = self._seen_by_message_id.get(
                        buffered_message.message.message_id
                    )
                    if message_id_records is not None:
                        message_id_records.remove(buffered_message)
                        if not message_id_records:
                            del self._seen_by_message_id[
                                buffered_message.message.message_id
                            ]
                self._seen_count -= 1
