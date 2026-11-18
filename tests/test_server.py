import logging
import unittest
from unittest.mock import MagicMock, patch

from cc_logger.server import main


class TestServerMain(unittest.TestCase):
    @patch("cc_logger.server.web.run_app")
    @patch(
        "cc_logger.server.Config.from_env",
        side_effect=ValueError("CHAT_NAME missing"),
    )
    @patch("cc_logger.server.configure_logging")
    def test_logs_fatal_configuration_error(
        self,
        configure_logging: MagicMock,
        from_env: MagicMock,
        run_app: MagicMock,
    ) -> None:
        with self.assertLogs("cc_logger.server", level="CRITICAL") as logs:
            with self.assertRaises(SystemExit):
                main()

        self.assertIn("Startup configuration failed", logs.output[0])
        self.assertIn("CHAT_NAME missing", logs.output[0])
        configure_logging.assert_called_once()
        from_env.assert_called_once()
        run_app.assert_not_called()

    @patch("cc_logger.server.logging.basicConfig")
    @patch(
        "cc_logger.server.configure_logging",
        side_effect=ValueError("Unsupported LOG_LEVEL: verbose"),
    )
    @patch("cc_logger.server.web.run_app")
    def test_logs_invalid_logging_configuration(
        self,
        run_app: MagicMock,
        configure_logging: MagicMock,
        basic_config: MagicMock,
    ) -> None:
        with self.assertLogs("cc_logger.server", level="CRITICAL") as logs:
            with self.assertRaises(SystemExit):
                main()

        self.assertIn("Logging configuration failed", logs.output[0])
        self.assertIn("Unsupported LOG_LEVEL", logs.output[0])
        basic_config.assert_called_once_with(level=logging.INFO, force=True)
        run_app.assert_not_called()


if __name__ == "__main__":
    unittest.main()
