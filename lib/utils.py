import logging
import sys
from logging import Logger

PORT_MIN = 0
PORT_MAX = 65535

logger: Logger = logging.getLogger(__name__)


# Define an inner function for validating the API_PORT
def ensure_valid_port(port: int) -> int:
    """Raise TypeError or ValueError if a port is invalid."""
    if not isinstance(port, int):
        msg = f"Port must be an integer, but got {type(port).__name__}: {port}"
        raise TypeError(msg)
    if not (PORT_MIN <= port <= PORT_MAX):
        msg = f"Port {port} is not in the valid range {PORT_MIN}-{PORT_MAX}"
        raise ValueError(msg)
    return port  # Return the valid port


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
    sys.exit(1)
