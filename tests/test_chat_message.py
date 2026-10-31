import unittest

from cc_logger.chat_message import ChatMessage


def make_payload(
    message_id: int = 1, timestamp: str = "2021-01-01T00:00:00.000000000Z"
) -> dict[str, object]:
    return {
        "id": message_id,
        "timestamp": timestamp,
        "chatType": "CLAN",
        "chatName": "IronForged",
        "sender": "Player",
        "message": "Hello",
    }


class TestChatMessage(unittest.TestCase):
    def test_accepts_message_id_above_signed_64_bit_range(self) -> None:
        message = ChatMessage.from_payload(make_payload(message_id=1 << 100))

        self.assertEqual(message.message_id, 1 << 100)

    def test_does_not_require_rank(self) -> None:
        message = ChatMessage.from_payload(make_payload())

        self.assertEqual(message.sender, "Player")

    def test_format_uses_discord_localized_timestamp(self) -> None:
        message = ChatMessage.from_payload(make_payload())

        self.assertEqual(
            message.format_discord(), '<t:1609459200:t> **Player** "Hello"\n'
        )

    def test_system_sender_is_omitted_and_content_italicized(self) -> None:
        payload = make_payload()
        payload["sender"] = "iRoNfOrGeD"
        payload["chatName"] = "IRONFORGED"
        message = ChatMessage.from_payload(payload)

        self.assertEqual(
            message.format_discord(),
            "-# <t:1609459200:t> *Hello*\n",
        )

    def test_sender_named_iron_forged_is_normal_when_not_chat_name(self) -> None:
        payload = make_payload()
        payload["sender"] = "Iron Forged"
        payload["chatName"] = "IronForged Clan"
        message = ChatMessage.from_payload(payload)

        self.assertEqual(
            message.format_discord(),
            '<t:1609459200:t> **Iron Forged** "Hello"\n',
        )

    def test_removes_runelite_image_tags_from_message(self) -> None:
        payload = make_payload()
        payload["message"] = "Hello <img=41> world"
        message = ChatMessage.from_payload(payload)

        self.assertEqual(message.message, "Hello world")

    def test_rejects_line_that_cannot_fit_webhook_prefix(self) -> None:
        payload = make_payload()
        payload["message"] = "x" * 1968

        with self.assertRaises(ValueError):
            ChatMessage.from_payload(payload)

    def test_rejects_naive_timestamp(self) -> None:
        payload = make_payload(timestamp="2021-01-01T00:00:00")

        with self.assertRaises(ValueError):
            ChatMessage.from_payload(payload)

    def test_rejects_invalid_chat_type(self) -> None:
        payload = make_payload()
        payload["chatType"] = "PUBLIC"

        with self.assertRaises(ValueError):
            ChatMessage.from_payload(payload)

    def test_rejects_friends_chat_type(self) -> None:
        payload = make_payload()
        payload["chatType"] = "FRIENDS"

        with self.assertRaises(ValueError):
            ChatMessage.from_payload(payload)

    def test_rejects_boolean_and_negative_message_ids(self) -> None:
        for message_id in (True, -1):
            with self.subTest(message_id=message_id):
                with self.assertRaises(ValueError):
                    ChatMessage.from_payload(make_payload(message_id=message_id))

    def test_rejects_invalid_or_missing_timestamp_timezone(self) -> None:
        for timestamp in ("not-a-timestamp", "2021-01-01T00:00:00", None):
            with self.subTest(timestamp=timestamp):
                payload = make_payload()
                payload["timestamp"] = timestamp
                with self.assertRaises(ValueError):
                    ChatMessage.from_payload(payload)

    def test_converts_timestamp_offset_to_utc(self) -> None:
        message = ChatMessage.from_payload(
            make_payload(timestamp="2021-01-01T05:30:00+05:30")
        )

        self.assertEqual(message.timestamp, 1609459200)

    def test_accepts_formatted_message_at_discord_character_limit(self) -> None:
        payload = make_payload()
        payload["message"] = ""
        empty_message = ChatMessage.from_payload(payload)
        available_characters = (
            2000 - len("\u200b\n") - len(empty_message.format_discord())
        )
        payload["message"] = "x" * available_characters

        message = ChatMessage.from_payload(payload)

        self.assertEqual(len(message.format_discord()) + len("\u200b\n"), 2000)

    def test_rejects_message_one_character_over_discord_limit(self) -> None:
        payload = make_payload()
        payload["message"] = ""
        empty_message = ChatMessage.from_payload(payload)
        available_characters = (
            2000 - len("\u200b\n") - len(empty_message.format_discord())
        )
        payload["message"] = "x" * (available_characters + 1)

        with self.assertRaises(ValueError):
            ChatMessage.from_payload(payload)


if __name__ == "__main__":
    unittest.main()
