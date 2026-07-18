"""Driver for the discord_bot project"""

import logging.handlers
from logging import Logger

import uvicorn

from lib.api import app
from lib.config import Config
from lib.logger_setup import configure_logger
from lib.utils import validate_port

logger: Logger = logging.getLogger(__name__)


def main() -> None:
    """Main driver function"""
    # Initialize config (this loads .env contents into system ENV)
    config = Config()
    if config.DRY_RUN:
        logger.info("Running in dry-run mode.")

    # Set up logging
    logger.info("Configuring logger...")
    configure_logger()

    # Validate the port number
    api_port = validate_port(int(config.API_PORT))

    # Start the FastAPI app using Uvicorn. This also starts the bot.
    logger.info("Starting FastAPI server...")
    uvicorn.run(
        app,
        host=config.API_HOST,  # Bind address; defaults to 0.0.0.0 in config
        port=api_port,
        log_config=None,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
