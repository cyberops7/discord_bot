import datetime as dt
import http
import json
import logging
import re
from types import TracebackType
from typing import Any, ClassVar, Literal, override

import colorlog
from uvicorn.logging import AccessFormatter

LOG_RECORD_BUILTIN_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class HealthCheckFilter(logging.Filter):
    """Filter to suppress successful /healthcheck logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Suppress logs for GET /healthcheck with a 200 status
        return not (
            hasattr(record, "getMessage")
            and "GET /healthcheck HTTP/1.1 200 OK" in record.getMessage()
        )


class CustomLogRecord(logging.LogRecord):
    """
    Custom LogRecord to add support for new attributes like client_addr.
    """

    def __init__(  # noqa: PLR0913
        self,
        name: str,
        level: int,
        pathname: str,
        lineno: int,
        msg: object,
        args: tuple[object, ...] | None,
        exc_info: (
            tuple[None, None, None]
            | tuple[type[BaseException], BaseException, TracebackType | None]
            | None
        ) = None,
        func: str | None = None,
        sinfo: str | None = None,
    ) -> None:
        super().__init__(
            name, level, pathname, lineno, msg, args, exc_info, func, sinfo
        )
        # Define any new attributes with default values
        self.client_addr: str | None = None
        self.http_version: str | None = None
        self.method: str | None = None
        self.path: str | None = None
        self.reason_phrase: str | None = None
        self.status_code: int | None = None
        self.status_color: str | None = None

    def __str__(self) -> str:
        """
        Provide a debug-friendly string representation of the log record,
        including the custom attributes.
        """
        return (
            f"{super().__str__()} "
            f"(client_addr={self.client_addr}, method={self.method}, path={self.path}, "
            f"status_code={self.status_code}, http_version={self.http_version})"
        )


def custom_log_record_factory(
    *args: Any,  # noqa: ANN401
    **kwargs: Any,  # noqa: ANN401
) -> logging.LogRecord:
    """
    Factory function to create CustomLogRecord instances.
    """
    return CustomLogRecord(*args, **kwargs)


class AccessLogFormatter(AccessFormatter):
    """
    A custom formatter that integrates the Uvicorn `AccessFormatter` for
    extra log fields/attributes with color support using `colorlog.ColoredFormatter`.
    """

    ANSI_COLOR_CODES: ClassVar[dict[str, str]] = {
        "black": "\033[30m",
        "red": "\033[31m",
        "bold_red": "\033[1;31m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "cyan": "\033[36m",
        "white": "\033[37m",
        "reset": "\033[0m",
    }
    # Define constants for HTTP status code ranges
    HTTP_STATUS_OK_MIN = 200
    HTTP_STATUS_OK_MAX = 299
    HTTP_STATUS_REDIRECT_MIN = 300
    HTTP_STATUS_REDIRECT_MAX = 399
    HTTP_STATUS_CLIENT_ERROR_MIN = 400
    HTTP_STATUS_CLIENT_ERROR_MAX = 499
    HTTP_STATUS_SERVER_ERROR_MIN = 500

    LOG_COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "cyan",
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "bold_red",
    }

    LOG_PATTERN: re.Pattern[str] = re.compile(
        r'(?P<client_addr>[\d.:]+) - "(?P<method>\w+) (?P<path>.+) '
        r'HTTP/(?P<http_version>[\d.]+)" (?P<status_code>\d+)'
    )

    STATUS_COLORS: ClassVar[dict[str, str]] = {
        "2xx": "green",
        "3xx": "yellow",
        "4xx": "red",
        "5xx": "bold_red",
    }

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "{",
        log_colors: dict[str, str] | None = None,
        reset: bool = True,
    ) -> None:
        # Initialize AccessFormatter
        fmt_clean = fmt.rstrip() if fmt else None
        super().__init__(fmt=fmt_clean, datefmt=datefmt, style=style)
        # Initialize colorlog.ColoredFormatter
        self.log_colors: dict[str, str] = log_colors or {}
        self.reset: bool = reset
        self.colored_formatter: colorlog.ColoredFormatter = colorlog.ColoredFormatter(
            fmt=fmt_clean,
            datefmt=datefmt,
            style=style,
            log_colors=log_colors,
            reset=reset,
        )

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802
        # Cast `record` to `CustomLogRecord` if required
        if isinstance(record, CustomLogRecord):
            if record.args is None and isinstance(record.msg, str):
                match = self.LOG_PATTERN.match(record.msg)
                if match:
                    record.client_addr = match.group("client_addr")
                    record.method = match.group("method")
                    record.path = match.group("path")
                    record.http_version = match.group("http_version")
                    record.status_code = int(match.group("status_code"))
                else:
                    # Fallback defaults if the regex fails
                    record.client_addr = "unknown"
                    record.method = "unknown"
                    record.path = "unknown"
                    record.http_version = "1.1"

            # Only assign additional attrs if we have a status_code
            if isinstance(record.status_code, int):
                # Get the reason phrase for the status code (e.g., "OK" for 200)
                record.reason_phrase = http.HTTPStatus(record.status_code).phrase
            if isinstance(record.status_code, int):
                # Assign the correct color for the status code
                record.status_color = self.get_status_color(record.status_code)

        return self.colored_formatter.format(record)

    def get_status_color(self, status_code: int) -> str:
        """Determine the color for the status code."""
        if self.HTTP_STATUS_OK_MIN <= status_code <= self.HTTP_STATUS_OK_MAX:
            return self.ANSI_COLOR_CODES.get(self.STATUS_COLORS["2xx"], "")
        if (
            self.HTTP_STATUS_REDIRECT_MIN
            <= status_code
            <= self.HTTP_STATUS_REDIRECT_MAX
        ):
            return self.ANSI_COLOR_CODES.get(self.STATUS_COLORS["3xx"], "")
        if (
            self.HTTP_STATUS_CLIENT_ERROR_MIN
            <= status_code
            <= self.HTTP_STATUS_CLIENT_ERROR_MAX
        ):
            return self.ANSI_COLOR_CODES.get(self.STATUS_COLORS["4xx"], "")
        if status_code >= self.HTTP_STATUS_SERVER_ERROR_MIN:
            return self.ANSI_COLOR_CODES.get(self.STATUS_COLORS["5xx"], "")
        return ""  # No color applied for unexpected codes


class JSONFormatter(logging.Formatter):
    def __init__(self, *, fmt_keys: dict[str, str] | None = None) -> None:
        super().__init__()
        self.fmt_keys: dict[str, str] = fmt_keys if fmt_keys is not None else {}

    @override
    def format(self, record: logging.LogRecord) -> str:
        message = self.prepare_log_dict(record)
        return json.dumps(message, default=str)

    def prepare_log_dict(
        self, record: logging.LogRecord
    ) -> dict[str, str | int | float]:
        always_fields = {
            "message": record.getMessage(),
            "timestamp": dt.datetime.fromtimestamp(
                record.created, tz=dt.UTC
            ).isoformat(),
        }
        if record.exc_info is not None:
            always_fields["exc_info"] = self.formatException(record.exc_info)

        if record.stack_info is not None:
            always_fields["stack_info"] = self.formatStack(record.stack_info)

        message = {
            key: msg_val
            if (msg_val := always_fields.get(val)) is not None
            else getattr(record, val)
            for key, val in self.fmt_keys.items()
        }
        message.update(always_fields)

        # Allow for extra keys to be passed to logging commands
        # Example usage: logger.info("log message", extra={"x": "hello"})
        message.update(
            {
                k: v
                for k, v in record.__dict__.items()
                if k not in LOG_RECORD_BUILTIN_ATTRS
            }
        )

        return message
