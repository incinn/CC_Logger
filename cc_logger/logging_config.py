from copy import copy
from datetime import datetime, timezone
import logging
import os

LOG_FORMAT = "%(asctime)s.%(msecs)03dZ %(levelname)-8s %(shortname)-8s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


class ReadableFormatter(logging.Formatter):
    def __init__(self) -> None:
        super().__init__(LOG_FORMAT, LOG_DATE_FORMAT)

    def format(self, record: logging.LogRecord) -> str:
        formatted_record = copy(record)
        setattr(formatted_record, "shortname", record.name.removeprefix("cc_logger."))
        return super().format(formatted_record)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return timestamp.strftime(datefmt or LOG_DATE_FORMAT)


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = logging.getLevelName(level_name)
    if not isinstance(level, int):
        raise ValueError(f"Unsupported LOG_LEVEL: {level_name}")

    handler = logging.StreamHandler()
    handler.setFormatter(ReadableFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
