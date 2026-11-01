import asyncio
from dataclasses import dataclass

from aiohttp import ClientSession, web

from cc_logger.chat_buffer import ChatBuffer
from cc_logger.config import Config


@dataclass(slots=True)
class RuntimeState:
    config: Config
    buffer: ChatBuffer
    session: ClientSession
    flush_lock: asyncio.Lock
    flush_task: asyncio.Task[None] | None = None


CONFIG_KEY = web.AppKey("config", Config)
STATE_KEY = web.AppKey("runtime_state", RuntimeState)
