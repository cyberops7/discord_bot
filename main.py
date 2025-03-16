"""Driver for the discord_bot project"""

import asyncio
import logging.handlers
import os
import sys
from logging import Logger

import discord
from discord import Intents
from dotenv import load_dotenv

from lib.api import start_fastapi_server
from lib.bot import DiscordBot
from lib.logger_setup import configure_logger
from lib.utils import validate_port

logger: Logger = logging.getLogger(__name__)


async def main() -> None:
    """Main driver function"""
    # Load .env contents into system ENV
    # !! Vars defined in .env will override any default env var values !!
    load_dotenv(override=True)

    # Set up logging
    configure_logger()

    # Validate the port number
    api_port = validate_port(int(os.getenv("API_PORT", "8080")))

    # Retrieve bot token
    logger.info("Retrieving bot token...")
    if not (bot_token := os.getenv("BOT_TOKEN")):
        logger.error("BOT_TOKEN is not set")
        sys.exit(1)

    # Initialize the bot
    logger.info("Initializing bot...")
    intents: Intents = discord.Intents.all()
    bot: DiscordBot = DiscordBot(intents=intents)

    # Create a task for the FastAPI server
    logger.info("Starting FastAPI server...")
    api_task = asyncio.create_task(start_fastapi_server(bot=bot, port=api_port))

    # Run the Discord bot
    logger.info("Starting Discord bot...")
    try:
        await bot.start(bot_token)
    except asyncio.CancelledError:
        logger.info("FastAPI server task cancelled.")
    finally:
        # Ensure FastAPI server task is finalized when bot stops
        api_task.cancel()
        try:
            await api_task
        except asyncio.CancelledError:
            logger.info("FastAPI server task cancelled.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
