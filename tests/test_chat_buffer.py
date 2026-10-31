import unittest

from cc_logger.chat_buffer import ChatBuffer
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


class TestChatBuffer(unittest.TestCase):
    def setUp(self) -> None:
        self.buffer = ChatBuffer(
            dedupe_ttl_seconds=60,
            max_pending_messages=2,
            max_dedupe_ids=10,
        )

    def test_adds_message_and_deduplicates_by_id(self) -> None:
        message = ChatMessage.from_payload(make_payload())

        self.assertEqual(self.buffer.add_batch([message], now=0), 1)
        self.assertEqual(self.buffer.add_batch([message], now=1), 0)
        self.assertEqual(self.buffer.pending_count, 1)

    def test_deduplicates_repeated_ids_inside_batch(self) -> None:
        message = ChatMessage.from_payload(make_payload())

        self.assertEqual(self.buffer.add_batch([message, message], now=0), 1)
        self.assertEqual(self.buffer.pending_count, 1)

    def test_expires_dedupe_ids(self) -> None:
        message = ChatMessage.from_payload(make_payload())
        self.buffer.add_batch([message], now=0)

        replacement = ChatMessage.from_payload(
            make_payload(timestamp="2021-01-01T00:00:01Z")
        )
        self.assertEqual(self.buffer.add_batch([replacement], now=61), 1)
        self.assertEqual(self.buffer.pending_count, 2)

    def test_rejects_batch_that_exceeds_memory_limit_atomically(self) -> None:
        first = ChatMessage.from_payload(make_payload(message_id=1))
        second = ChatMessage.from_payload(make_payload(message_id=2))
        third = ChatMessage.from_payload(make_payload(message_id=3))
        self.buffer.add_batch([first], now=0)

        self.assertIsNone(self.buffer.add_batch([second, third], now=1))
        self.assertEqual(self.buffer.pending_count, 1)
        self.assertEqual(self.buffer.add_batch([second], now=1), 1)

    def test_chunks_lines_under_discord_limit(self) -> None:
        first = ChatMessage.from_payload(make_payload(message_id=1))
        second_payload = make_payload(message_id=2)
        second_payload["message"] = "x" * 1950
        second = ChatMessage.from_payload(second_payload)
        self.buffer = ChatBuffer(max_pending_messages=5, max_dedupe_ids=10)
        self.buffer.add_batch([first, second], now=0)

        content, count = self.buffer.peek_chunk(max_chars=100)

        self.assertEqual(count, 1)
        self.assertEqual(content, first.format_discord())

    def test_rejects_batch_that_exceeds_dedupe_limit_atomically(self) -> None:
        self.buffer = ChatBuffer(
            dedupe_ttl_seconds=60,
            max_pending_messages=5,
            max_dedupe_ids=1,
        )
        first = ChatMessage.from_payload(make_payload(message_id=1))
        second = ChatMessage.from_payload(make_payload(message_id=2))

        self.assertEqual(self.buffer.add_batch([first], now=0), 1)
        self.assertIsNone(self.buffer.add_batch([second], now=1))
        self.assertEqual(self.buffer.pending_count, 1)
        self.assertEqual(self.buffer.add_batch([second], now=61), 1)

    def test_peek_chunk_includes_line_only_when_it_fits(self) -> None:
        message = ChatMessage.from_payload(make_payload())
        self.buffer.add_batch([message], now=0)
        line = message.format_discord()

        self.assertEqual(self.buffer.peek_chunk(max_chars=len(line)), (line, 1))
        self.assertIsNone(self.buffer.peek_chunk(max_chars=len(line) - 1))

    def test_discard_rejects_counts_outside_pending_range(self) -> None:
        for count in (-1, 1):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    self.buffer.discard(count)

    def test_rejects_nonpositive_buffer_limits(self) -> None:
        for options in (
            {"dedupe_ttl_seconds": 0},
            {"max_pending_messages": 0},
            {"max_dedupe_ids": 0},
        ):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    ChatBuffer(**options)


if __name__ == "__main__":
    unittest.main()
