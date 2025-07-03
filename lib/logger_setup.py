"""Logging library - configure logging from a yaml config file"""

import atexit
import logging
import logging.config
import logging.handlers
from logging import Logger
from pathlib import Path
from typing import Any

import yaml

from lib import config_parser
from lib.logger_extras import custom_log_record_factory

# change this to DEBUG if debugging logger initialization
logger: Logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def configure_logger(file_path: str = "conf/logger.yaml") -> None:
    """Set up logging using a YAML file"""
    logger.info("Loading logging configuration from YAML file...")

    # Set the global log record factory to use CustomLogRecord
    logging.setLogRecordFactory(custom_log_record_factory)

    try:
        yaml_path: Path = Path(file_path)
        with Path.open(yaml_path, encoding="utf-8") as yaml_file:
            try:
                yaml_config: dict[str, Any] = yaml.safe_load(yaml_file)
                logger.debug("Read YAML config: %s", yaml_config)
                yaml_config_resolved = config_parser.resolve_values(yaml_config)
                logger.debug("Resolved YAML config: %s", yaml_config_resolved)
                logging.config.dictConfig(yaml_config_resolved)
                logger.info("Logging configuration loaded from YAML file.")
                logger.debug("Logging configuration: %s", yaml_config_resolved)
            except yaml.YAMLError:
                logger.exception("Error parsing YAML file.")
            except (AttributeError, KeyError, TypeError, ValueError):
                logger.exception("Error in logging configuration.")
            else:
                start_queue_listeners()
                return
    except (FileNotFoundError, IsADirectoryError, OSError, PermissionError):
        logger.exception("Error reading logging configuration file.")
    # Apply basic logging as a fallback
    logging.basicConfig(level=logging.INFO)
    logger.info("Default logging configuration applied.")


def get_all_handlers() -> set[logging.Handler]:
    """
    Retrieve all handlers from all loggers, including the root logger.
    Returns a set of unique handlers.
    """
    # Start with the root logger
    all_handlers: set[logging.Handler] = set(logging.root.handlers)

    # Add handlers from all other loggers
    for logger_obj in logging.Logger.manager.loggerDict.values():
        if isinstance(logger_obj, logging.Logger):
            all_handlers.update(logger_obj.handlers)

    # Return the unique set of handlers
    return all_handlers


def start_queue_listeners() -> None:
    """
    Find all handlers whose names start with 'queue' and start their listeners.
    """
    logger.info("Checking for queue handler listeners...")
    all_handlers = get_all_handlers()

    if not all_handlers:
        logger.warning("No handlers found.")
        return

    for handler_name in all_handlers:  # Iterate through all registered handlers
        # Extract handler instance (some entries in `_handlerList` are weakrefs)
        try:
            # Yes, this is dumb to have the intermediary handler_func,
            # but this was the only way to make both ruff and pyre happy
            if callable(handler_name):
                handler_func = handler_name
                handler = handler_func()
            else:
                handler = handler_name

            if not isinstance(
                handler, logging.Handler
            ):  # Ensure it is type logging.Handler
                logger.warning("Invalid handler type: %s", type(handler))
                continue
        except ReferenceError as e:
            logger.warning("Weak reference expired for handler %s: %s", handler_name, e)
            continue
        except TypeError as e:
            logger.warning("Type error when processing handler %s: %s", handler_name, e)
            continue

        if (
            handler
            and hasattr(handler, "name")
            and handler.name
            and handler.name.startswith("queue")
        ):
            logger.info("Found queue handler: %s", handler.name)
            listener = getattr(handler, "listener", None)
            if listener:
                logger.info("Starting listener for handler: %s", handler.name)
                listener.start()
                # Ensure the listener's stop method is called on script exit
                atexit.register(listener.stop)
            else:
                logger.warning("No listener found for handler: %s", handler.name)
