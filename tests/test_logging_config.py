import logging
import os
import unittest
from unittest.mock import MagicMock, patch

from cc_logger.logging_config import ReadableFormatter, configure_logging


class TestConfigureLogging(unittest.TestCase):
    @patch.dict(os.environ, {"LOG_LEVEL": "debug"}, clear=True)
    @patch("cc_logger.logging_config.logging.basicConfig")
    def test_configures_readable_console_format(self, basic_config: MagicMock) -> None:
        configure_logging()

        basic_config.assert_called_once()
        options = basic_config.call_args.kwargs
        self.assertEqual(options["level"], logging.DEBUG)
        self.assertTrue(options["force"])
        self.assertEqual(len(options["handlers"]), 1)
        self.assertIsInstance(options["handlers"][0].formatter, ReadableFormatter)

    def test_formatter_uses_utc_milliseconds_and_short_logger_name(self) -> None:
        record = logging.LogRecord(
            "cc_logger.ingest",
            logging.INFO,
            __file__,
            1,
            "Received %d messages",
            (3,),
            None,
        )
        record.created = 0.123
        record.msecs = 123

        self.assertEqual(
            ReadableFormatter().format(record),
            "1970-01-01T00:00:00.123Z INFO     ingest   | Received 3 messages",
        )

    @patch.dict(os.environ, {"LOG_LEVEL": "verbose"}, clear=True)
    def test_rejects_invalid_log_level(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported LOG_LEVEL"):
            configure_logging()


if __name__ == "__main__":
    unittest.main()
