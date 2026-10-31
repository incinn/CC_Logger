import asyncio
import logging

from aiohttp import ClientSession, ClientTimeout, web

from cc_logger.chat_buffer import ChatBuffer
from cc_logger.config import Config
from cc_logger.delivery import flush_loop, flush_pending
from cc_logger.ingest import receive_messages
from cc_logger.runtime import CONFIG_KEY, STATE_KEY, RuntimeState

MAX_REQUEST_BYTES = 1_048_576


async def _start_app(app: web.Application) -> None:
    config = app[CONFIG_KEY]
    state = RuntimeState(
        config=config,
        buffer=ChatBuffer(
            dedupe_ttl_seconds=config.dedupe_ttl_seconds,
            max_pending_messages=config.max_pending_messages,
            max_dedupe_ids=config.max_dedupe_ids,
        ),
        session=ClientSession(timeout=ClientTimeout(total=10)),
        flush_lock=asyncio.Lock(),
    )
    app[STATE_KEY] = state
    state.flush_task = asyncio.create_task(flush_loop(state))


async def _stop_app(app: web.Application) -> None:
    state = app[STATE_KEY]
    if state.flush_task is not None:
        state.flush_task.cancel()
        await asyncio.gather(state.flush_task, return_exceptions=True)
    await flush_pending(state)
    await state.session.close()


def create_app(config: Config) -> web.Application:
    app = web.Application(client_max_size=MAX_REQUEST_BYTES)
    app[CONFIG_KEY] = config
    app.router.add_post("/messages", receive_messages)
    app.on_startup.append(_start_app)
    app.on_cleanup.append(_stop_app)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = Config.from_env()
    web.run_app(create_app(config), host=config.host, port=config.port)


if __name__ == "__main__":
    main()
