"""Driver for the discord_bot project"""

import logging.handlers
import os
from logging import Logger

import uvicorn
from dotenv import load_dotenv

from lib.api import app
from lib.logger_setup import configure_logger
from lib.utils import validate_port

logger: Logger = logging.getLogger(__name__)


def main() -> None:
    """Main driver function"""
    # Load .env contents into system ENV
    # !! Vars defined in .env will override any default env var values !!
    logger.info("Loading environment variables from .env file (if present)...")
    load_dotenv(override=True)

    # Set up logging
    logger.info("Configuring logger...")
    configure_logger()

    # Validate the port number
    api_port = validate_port(int(os.getenv("API_PORT", "8080")))

    # Start the FastAPI app using Uvicorn. This also starts the bot.
    logger.info("Starting FastAPI server...")
    # TODO @cyberops7: use os.getenv("API_HOST", "127.0.0.1") instead of 0.0.0.0
    uvicorn.run(
        app,
        host="0.0.0.0",  # Bind to all network interfaces # noqa: S104
        port=api_port,
        log_config=None,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
