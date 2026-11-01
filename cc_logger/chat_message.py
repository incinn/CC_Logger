from dataclasses import dataclass
from datetime import datetime, timezone
import re

DISCORD_MESSAGE_LIMIT = 2000
MAX_PLUGIN_BATCH_SIZE = 30
WEBHOOK_CONTENT_PREFIX = "\u200b\n"
RUNELITE_IMAGE_TAG_PATTERN = re.compile(r"<img=\d+>")


@dataclass(frozen=True, slots=True)
class ChatMessage:
    message_id: int
    timestamp: int
    sender: str
    chat_name: str
    message: str

    @classmethod
    def from_payload(cls, payload: object) -> "ChatMessage":
        if not isinstance(payload, dict):
            raise ValueError("Each message must be an object")

        message_id = payload.get("id")
        if isinstance(message_id, bool) or not isinstance(message_id, int):
            raise ValueError("Message id must be an integer")
        if message_id < 0:
            raise ValueError("Message id must be a non-negative integer")

        timestamp = payload.get("timestamp")
        if not isinstance(timestamp, str):
            raise ValueError("Message timestamp must be a string")
        try:
            parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Message timestamp must be ISO-8601") from error
        if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
            raise ValueError("Message timestamp must include a timezone")
        try:
            timestamp_unix = int(parsed_timestamp.astimezone(timezone.utc).timestamp())
        except (OverflowError, OSError, ValueError) as error:
            raise ValueError("Message timestamp is outside supported range") from error

        chat_type = payload.get("chatType")
        if chat_type != "CLAN":
            raise ValueError("Only CLAN chat messages are accepted")
        chat_name = payload.get("chatName")
        if not isinstance(chat_name, str):
            raise ValueError("chatName must be a string")
        if not isinstance(payload.get("sender"), str):
            raise ValueError("sender must be a string")
        message = payload.get("message")
        if not isinstance(message, str):
            raise ValueError("message must be a string")
        if RUNELITE_IMAGE_TAG_PATTERN.search(message):
            message = RUNELITE_IMAGE_TAG_PATTERN.sub(" ", message)
            message = re.sub(r" {2,}", " ", message).strip()

        result = cls(
            message_id=message_id,
            timestamp=timestamp_unix,
            sender=payload["sender"],
            chat_name=chat_name,
            message=message,
        )
        if (
            len(result.format_discord()) + len(WEBHOOK_CONTENT_PREFIX)
            > DISCORD_MESSAGE_LIMIT
        ):
            raise ValueError("Formatted message exceeds Discord's 2000-character limit")
        return result

    def format_discord(self, confidence: int = 1) -> str:
        if (
            isinstance(confidence, bool)
            or not isinstance(confidence, int)
            or confidence < 1
        ):
            raise ValueError("confidence must be a positive integer")

        is_system = self.sender.casefold() == self.chat_name.casefold()
        if is_system:
            return f"-# <t:{self.timestamp}:t> *{self.message}* ({confidence})\n"
        return f'<t:{self.timestamp}:t> **{self.sender}** "{self.message}" ({confidence})\n'
