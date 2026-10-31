import asyncio
from dataclasses import dataclass
from importlib.metadata import version
import logging
import math
import random

from aiohttp import ClientError

from cc_logger.chat_message import WEBHOOK_CONTENT_PREFIX
from cc_logger.runtime import RuntimeState

logger = logging.getLogger("cc_logger")
MAX_RETRY_DELAY_SECONDS = 300
ONLINE_STATUS_MESSAGE = f":green_circle: ONLINE v{version('cc-logger')}"
OFFLINE_STATUS_MESSAGE = ":red_circle: OFFLINE"


@dataclass(frozen=True, slots=True)
class FlushResult:
    success: bool
    retry_after_seconds: float | None = None


async def send_status(state: RuntimeState, message: str) -> bool:
    try:
        async with state.session.post(
            state.config.discord_webhook_url,
            json={"content": message, "allowed_mentions": {"parse": []}},
        ) as response:
            if not 200 <= response.status < 300:
                logger.warning(
                    "Discord webhook returned HTTP %s for status notification",
                    response.status,
                )
                return False
    except (ClientError, asyncio.TimeoutError) as error:
        logger.warning(
            "Discord webhook status notification failed (%s)",
            type(error).__name__,
        )
        return False
    except Exception:
        logger.exception("Unexpected error sending Discord webhook status notification")
        return False
    return True


async def flush_pending(state: RuntimeState) -> FlushResult:
    async with state.flush_lock:
        while chunk := state.buffer.peek_chunk():
            content, count = chunk
            try:
                async with state.session.post(
                    state.config.discord_webhook_url,
                    json={
                        "content": f"{WEBHOOK_CONTENT_PREFIX}{content}",
                        "allowed_mentions": {"parse": []},
                    },
                ) as response:
                    if not 200 <= response.status < 300:
                        retry_after_seconds = None
                        if response.status == 429:
                            retry_after_seconds = _parse_retry_after(
                                response.headers.get("Retry-After")
                            )
                        logger.warning(
                            "Discord webhook returned HTTP %s; keeping messages buffered",
                            response.status,
                        )
                        return FlushResult(
                            success=False,
                            retry_after_seconds=retry_after_seconds,
                        )
            except (ClientError, asyncio.TimeoutError) as error:
                logger.warning(
                    "Discord webhook request failed (%s); keeping messages buffered",
                    type(error).__name__,
                )
                return FlushResult(success=False)

            state.buffer.discard(count)
        return FlushResult(success=True)


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def _retry_delay(
    interval: float, failure_count: int, retry_after_seconds: float | None = None
) -> float:
    if failure_count < 1:
        raise ValueError("failure_count must be greater than zero")

    max_delay = max(interval, MAX_RETRY_DELAY_SECONDS)
    exponent = min(
        math.log2(interval) + failure_count - 1,
        math.log2(max_delay),
    )
    backoff = 2**exponent
    jittered_backoff = min(random.uniform(backoff * 0.5, backoff * 1.5), max_delay)
    if retry_after_seconds is not None:
        return max(jittered_backoff, retry_after_seconds)
    return jittered_backoff


async def flush_loop(state: RuntimeState) -> None:
    interval = state.config.flush_interval_seconds
    next_delay = interval
    failure_count = 0
    while True:
        await asyncio.sleep(next_delay)
        try:
            result = await flush_pending(state)
        except Exception:
            logger.exception("Unexpected error while flushing Discord messages")
            result = FlushResult(success=False)

        if result.success:
            failure_count = 0
            next_delay = interval
        else:
            failure_count += 1
            next_delay = _retry_delay(
                interval, failure_count, result.retry_after_seconds
            )
