import logging
import sys
from collections.abc import Awaitable, Callable
from logging import Logger

import pytest

# TODO @cyberops7: move PORT_MIN/MAX to config
PORT_MIN = 0
PORT_MAX = 65535

logger: Logger = logging.getLogger(__name__)


def async_test(func: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
    """Wrapper for pytest.mark.asyncio that handles Pyre type issues"""
    return pytest.mark.asyncio(func)  # type: ignore[56]


def ensure_valid_port(port: int) -> int:
    """Raise TypeError or ValueError if a port is invalid."""
    if not isinstance(port, int):
        msg = f"Port must be an integer, but got {type(port).__name__}: {port}"
        raise TypeError(msg)
    if not (PORT_MIN <= port <= PORT_MAX):
        msg = f"Port {port} is not in the valid range {PORT_MIN}-{PORT_MAX}"
        raise ValueError(msg)
    return port


def validate_port(port: int) -> int:
    """
    Wrapper to validate the port and handle errors.
    """
    logger.debug("Validating targeted port: %s...", port)
    try:
        return ensure_valid_port(port)  # Abstract raising logic here
    except TypeError:
        logger.exception("Targeted port is not an integer: %s", port)
    except ValueError:
        logger.exception("Targeted port is not valid: %s", port)
    logger.error("Exiting due to invalid port.")
    sys.exit(1)
