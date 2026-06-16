"""Bot entry point — long-polling runner."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from ..config import get_settings
from .handlers import router


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()

    # Uploading audio (tens of MB) over a slow link can take minutes — the default
    # 60s request timeout would abort it, so give file transfers plenty of room.
    session = AiohttpSession(timeout=settings.request_timeout_seconds)
    bot = Bot(
        token=settings.telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logging.info("BookBot is starting (long polling)…")
    await dp.start_polling(bot)


def run() -> None:
    """Console-script / module entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
