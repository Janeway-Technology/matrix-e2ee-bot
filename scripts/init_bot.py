"""
One-shot script to verify bot credentials and pre-populate the crypto store.
Run this before the first container start to catch configuration errors early.

Usage:
    python scripts/init_bot.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.config import settings
from app.matrix_client import MatrixClientManager
from app.utils.logger import setup_logging, get_logger

setup_logging("INFO")
logger = get_logger("init_bot")


async def main() -> None:
    logger.info("init_bot_start", user=settings.matrix_user, homeserver=settings.matrix_homeserver)
    mgr = MatrixClientManager(settings)
    try:
        await mgr.start()
        health = mgr.health()
        logger.info("init_bot_success", health=health)
    finally:
        await mgr.stop()


if __name__ == "__main__":
    asyncio.run(main())
