import logging
import os
import unittest
from unittest.mock import MagicMock, patch

from cc_logger.logging_config import configure_logging


class TestConfigureLogging(unittest.TestCase):
    @patch.dict(os.environ, {"LOG_LEVEL": "debug"}, clear=True)
    @patch("cc_logger.logging_config.logging.basicConfig")
    def test_configures_readable_console_format(self, basic_config: MagicMock) -> None:
        configure_logging()

        basic_config.assert_called_once_with(
            level=logging.DEBUG,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            force=True,
        )

    @patch.dict(os.environ, {"LOG_LEVEL": "verbose"}, clear=True)
    def test_rejects_invalid_log_level(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unsupported LOG_LEVEL"):
            configure_logging()


if __name__ == "__main__":
    unittest.main()
