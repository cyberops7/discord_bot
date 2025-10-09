"""Unit tests for logger_extras.py"""

import datetime as dt
import json
import logging
import re
import sys
from unittest.mock import MagicMock, patch

import colorlog
import pytest

from lib.logger_extras import (
    LOG_RECORD_BUILTIN_ATTRS,
    AccessLogFormatter,
    CustomLogRecord,
    HealthCheckFilter,
    JSONFormatter,
    custom_log_record_factory,
)


class TestHealthCheckFilter:
    """Test HealthCheckFilter class"""

    @pytest.fixture
    def health_filter(self) -> HealthCheckFilter:
        """Create a HealthCheckFilter instance"""
        return HealthCheckFilter()

    def test_filter_allows_non_healthcheck_log(
        self, health_filter: HealthCheckFilter
    ) -> None:
        """Test that filter allows non-healthcheck logs through"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Regular log message",
            args=(),
            exc_info=None,
        )

        result = health_filter.filter(record)
        assert result is True

    def test_filter_suppresses_healthcheck_log(
        self, health_filter: HealthCheckFilter
    ) -> None:
        """Test that filter suppresses successful healthcheck logs"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="GET /healthcheck HTTP/1.1 200 OK",
            args=(),
            exc_info=None,
        )

        result = health_filter.filter(record)
        assert result is False

    def test_filter_allows_healthcheck_with_different_status(
        self, health_filter: HealthCheckFilter
    ) -> None:
        """Test that filter allows healthcheck logs with non-200 status"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="GET /healthcheck HTTP/1.1 404 Not Found",
            args=(),
            exc_info=None,
        )

        result = health_filter.filter(record)
        assert result is True

    def test_filter_allows_partial_healthcheck_message(
        self, health_filter: HealthCheckFilter
    ) -> None:
        """Test that filter allows logs with partial healthcheck patterns"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="GET /healthcheck",
            args=(),
            exc_info=None,
        )

        result = health_filter.filter(record)
        assert result is True

    def test_filter_handles_record_without_getmessage(
        self, health_filter: HealthCheckFilter
    ) -> None:
        """Test that filter handles records without a getMessage method"""

        # Create a mock record that mimics LogRecord but without a getMessage method
        mock_record = MagicMock(spec=logging.LogRecord)
        # Remove the getMessage method to test the exception handling
        del mock_record.getMessage

        result = health_filter.filter(mock_record)
        assert result is True

    def test_filter_with_complex_healthcheck_log(
        self, health_filter: HealthCheckFilter
    ) -> None:
        """Test filter with a complete `healthcheck log message"""
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname="/path/to/uvicorn.py",
            lineno=100,
            msg='127.0.0.1:54321 - "GET /healthcheck HTTP/1.1 200 OK"',
            args=(),
            exc_info=None,
        )

        result = health_filter.filter(record)
        assert result is False

    def test_filter_with_healthcheck_substring_in_larger_message(
        self, health_filter: HealthCheckFilter
    ) -> None:
        """Test filter when a healthcheck pattern is part of a larger message"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Processing request: GET /healthcheck HTTP/1.1 200 OK - took 5ms",
            args=(),
            exc_info=None,
        )

        result = health_filter.filter(record)
        assert result is False


class TestCustomLogRecord:
    """Test CustomLogRecord class"""

    def test_init_default_values(self) -> None:
        """Test CustomLogRecord initialization with default values"""
        record = CustomLogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
        )

        assert record.name == "test_logger"
        assert record.levelno == logging.INFO
        assert record.pathname == "/test/path.py"
        assert record.lineno == 42
        assert record.msg == "Test message"
        assert record.args == ()
        assert record.client_addr is None
        assert record.http_version is None
        assert record.method is None
        assert record.path is None
        assert record.reason_phrase is None
        assert record.status_code is None
        assert record.status_color is None

    def test_init_with_all_parameters(self) -> None:
        """Test CustomLogRecord initialization with all parameters"""
        exc_info = (ValueError, ValueError("test error"), None)
        record = CustomLogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=("arg1", "arg2"),
            exc_info=exc_info,
            func="test_function",
            sinfo="stack info",
        )

        assert record.name == "test_logger"
        assert record.levelno == logging.ERROR
        assert record.pathname == "/test/path.py"
        assert record.lineno == 42
        assert record.msg == "Test message"
        assert record.args == ("arg1", "arg2")
        assert record.exc_info == exc_info
        assert record.funcName == "test_function"
        assert record.stack_info == "stack info"

    def test_str_method(self) -> None:
        """Test CustomLogRecord __str__ method"""
        record = CustomLogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
        )
        record.client_addr = "127.0.0.1"
        record.method = "GET"
        record.path = "/api/test"
        record.status_code = 200
        record.http_version = "1.1"

        result = str(record)
        assert "Test message" in result
        assert "client_addr=127.0.0.1" in result
        assert "method=GET" in result
        assert "path=/api/test" in result
        assert "status_code=200" in result
        assert "http_version=1.1" in result


class TestCustomLogRecordFactory:
    """Test the custom_log_record_factory function"""

    def test_factory_creates_custom_log_record(self) -> None:
        """Test that the factory creates CustomLogRecord instances"""
        record = custom_log_record_factory(
            "test_logger",
            logging.INFO,
            "/test/path.py",
            42,
            "Test message",
            (),
        )

        assert isinstance(record, CustomLogRecord)
        assert record.name == "test_logger"
        assert record.levelno == logging.INFO
        assert record.pathname == "/test/path.py"
        assert record.lineno == 42
        assert record.msg == "Test message"
        assert record.args == ()

    def test_factory_with_kwargs(self) -> None:
        """Test factory with keyword arguments"""
        record = custom_log_record_factory(
            "test_logger",
            logging.ERROR,
            "/test/path.py",
            42,
            "Test message",
            (),
            exc_info=None,
            func="test_func",
            sinfo="stack",
        )

        assert isinstance(record, CustomLogRecord)
        assert record.funcName == "test_func"
        assert record.stack_info == "stack"


class TestAccessLogFormatter:
    """Test AccessLogFormatter class"""

    @pytest.fixture
    def formatter(self) -> AccessLogFormatter:
        """Create a basic AccessLogFormatter instance"""
        return AccessLogFormatter()

    @pytest.fixture
    def custom_formatter(self) -> AccessLogFormatter:
        """Create a customized AccessLogFormatter instance"""
        return AccessLogFormatter(
            fmt="{levelname} - {message}",
            datefmt="%Y-%m-%d %H:%M:%S",
            style="{",
            log_colors={"INFO": "blue"},
            reset=False,
        )

    def test_init_default_values(self, formatter: AccessLogFormatter) -> None:
        """Test AccessLogFormatter initialization with default values"""
        assert formatter.log_colors == {}
        assert formatter.reset is True
        assert isinstance(formatter.colored_formatter, colorlog.ColoredFormatter)

    def test_init_with_custom_values(
        self, custom_formatter: AccessLogFormatter
    ) -> None:
        """Test AccessLogFormatter initialization with custom values"""
        assert custom_formatter.log_colors == {"INFO": "blue"}
        assert custom_formatter.reset is False
        assert isinstance(custom_formatter.colored_formatter, colorlog.ColoredFormatter)

    def test_init_with_fmt_none(self) -> None:
        """Test AccessLogFormatter initialization with fmt=None"""
        formatter = AccessLogFormatter(fmt=None)
        assert isinstance(formatter.colored_formatter, colorlog.ColoredFormatter)

    def test_init_with_fmt_trailing_whitespace(self) -> None:
        """Test AccessLogFormatter initialization strips trailing whitespace"""
        formatter = AccessLogFormatter(fmt="{message}   ")
        # This tests that fmt_clean is used after stripping
        assert isinstance(formatter.colored_formatter, colorlog.ColoredFormatter)

    @pytest.mark.parametrize(
        ("status_code", "expected_color_key"),
        [
            (200, "2xx"),
            (201, "2xx"),
            (299, "2xx"),
            (300, "3xx"),
            (301, "3xx"),
            (399, "3xx"),
            (400, "4xx"),
            (404, "4xx"),
            (499, "4xx"),
            (500, "5xx"),
            (502, "5xx"),
            (599, "5xx"),
            (100, ""),  # Unexpected code
            (199, ""),  # Unexpected code
            (600, "5xx"),  # >= 500
        ],
    )
    def test_get_status_color(
        self, formatter: AccessLogFormatter, status_code: int, expected_color_key: str
    ) -> None:
        """Test the get_status_color method with various status codes"""
        result = formatter.get_status_color(status_code)
        if expected_color_key:
            expected_color = formatter.ANSI_COLOR_CODES.get(
                formatter.STATUS_COLORS[expected_color_key], ""
            )
            assert result == expected_color
        else:
            assert result == ""

    def test_format_message_with_custom_log_record_matching_pattern(
        self, formatter: AccessLogFormatter
    ) -> None:
        """Test formatMessage with CustomLogRecord that matches LOG_PATTERN"""
        record = CustomLogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg='127.0.0.1 - "GET /api/test HTTP/1.1" 200',
            args=None,
        )

        with patch.object(
            formatter.colored_formatter, "format", return_value="formatted"
        ) as mock_format:
            result = formatter.formatMessage(record)

            assert result == "formatted"
            assert record.client_addr == "127.0.0.1"
            assert record.method == "GET"
            assert record.path == "/api/test"
            assert record.http_version == "1.1"
            assert record.status_code == 200
            assert record.reason_phrase == "OK"
            assert record.status_color == formatter.ANSI_COLOR_CODES.get("green", "")
            mock_format.assert_called_once_with(record)

    def test_format_message_with_custom_log_record_non_matching_pattern(
        self, formatter: AccessLogFormatter
    ) -> None:
        """Test formatMessage with CustomLogRecord that doesn't match LOG_PATTERN"""
        record = CustomLogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Invalid log message format",
            args=None,
        )

        with patch.object(
            formatter.colored_formatter, "format", return_value="formatted"
        ) as mock_format:
            result = formatter.formatMessage(record)

            assert result == "formatted"
            assert record.client_addr == "unknown"
            assert record.method == "unknown"
            assert record.path == "unknown"
            assert record.http_version == "1.1"
            assert record.reason_phrase is None
            assert record.status_code is None
            assert record.status_color is None
            mock_format.assert_called_once_with(record)

    def test_format_message_with_custom_log_record_with_args(
        self, formatter: AccessLogFormatter
    ) -> None:
        """Test formatMessage with CustomLogRecord that has args (skips parsing)"""
        record = CustomLogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message with %s",
            args=("arg1",),
        )

        with patch.object(
            formatter.colored_formatter, "format", return_value="formatted"
        ) as mock_format:
            result = formatter.formatMessage(record)

            assert result == "formatted"
            # Should not modify these attributes when args is not None
            assert record.client_addr is None
            assert record.method is None
            mock_format.assert_called_once_with(record)

    def test_format_message_with_non_custom_log_record(
        self, formatter: AccessLogFormatter
    ) -> None:
        """Test formatMessage with standard LogRecord"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        with patch.object(
            formatter.colored_formatter, "format", return_value="formatted"
        ) as mock_format:
            result = formatter.formatMessage(record)

            assert result == "formatted"
            mock_format.assert_called_once_with(record)

    def test_format_message_with_invalid_status_code(
        self, formatter: AccessLogFormatter
    ) -> None:
        """Test formatMessage with invalid status code for http.HTTPStatus"""
        record = CustomLogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg='127.0.0.1 - "GET /api/test HTTP/1.1" 999',
            args=None,
        )

        with (
            patch.object(
                formatter.colored_formatter, "format", return_value="formatted"
            ),
            pytest.raises(ValueError, match="999"),
        ):
            formatter.formatMessage(record)

    def test_format_message_with_non_string_msg(
        self, formatter: AccessLogFormatter
    ) -> None:
        """Test formatMessage with non-string msg"""
        record = CustomLogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg=123,  # Non-string message
            args=None,
        )

        with patch.object(
            formatter.colored_formatter, "format", return_value="formatted"
        ) as mock_format:
            result = formatter.formatMessage(record)

            assert result == "formatted"
            # Should not try to match the pattern on non-string msg
            assert record.client_addr is None
            mock_format.assert_called_once_with(record)

    def test_class_constants(self) -> None:
        """Test that class constants are properly defined"""
        assert AccessLogFormatter.HTTP_STATUS_OK_MIN == 200
        assert AccessLogFormatter.HTTP_STATUS_OK_MAX == 299
        assert AccessLogFormatter.HTTP_STATUS_REDIRECT_MIN == 300
        assert AccessLogFormatter.HTTP_STATUS_REDIRECT_MAX == 399
        assert AccessLogFormatter.HTTP_STATUS_CLIENT_ERROR_MIN == 400
        assert AccessLogFormatter.HTTP_STATUS_CLIENT_ERROR_MAX == 499
        assert AccessLogFormatter.HTTP_STATUS_SERVER_ERROR_MIN == 500

        assert "green" in AccessLogFormatter.ANSI_COLOR_CODES
        assert "red" in AccessLogFormatter.ANSI_COLOR_CODES
        assert "reset" in AccessLogFormatter.ANSI_COLOR_CODES

        assert "DEBUG" in AccessLogFormatter.LOG_COLORS
        assert "INFO" in AccessLogFormatter.LOG_COLORS
        assert "WARNING" in AccessLogFormatter.LOG_COLORS
        assert "ERROR" in AccessLogFormatter.LOG_COLORS
        assert "CRITICAL" in AccessLogFormatter.LOG_COLORS

        assert "2xx" in AccessLogFormatter.STATUS_COLORS
        assert "3xx" in AccessLogFormatter.STATUS_COLORS
        assert "4xx" in AccessLogFormatter.STATUS_COLORS
        assert "5xx" in AccessLogFormatter.STATUS_COLORS

        assert isinstance(AccessLogFormatter.LOG_PATTERN, re.Pattern)

    def test_log_pattern_regex(self) -> None:
        """Test the LOG_PATTERN regex with various inputs"""
        pattern = AccessLogFormatter.LOG_PATTERN

        # Valid patterns
        valid_cases = [
            '127.0.0.1 - "GET /api/test HTTP/1.1" 200',
            '192.168.1.1 - "POST /login HTTP/2.0" 302',
            '::1 - "PUT /data HTTP/1.0" 404',
        ]

        for case in valid_cases:
            match = pattern.match(case)
            assert match is not None
            assert "client_addr" in match.groupdict()
            assert "method" in match.groupdict()
            assert "path" in match.groupdict()
            assert "http_version" in match.groupdict()
            assert "status_code" in match.groupdict()

        # Invalid patterns
        invalid_cases = [
            "Invalid log format",
            "127.0.0.1 - GET /api/test HTTP/1.1 200",  # Missing quotes
            "",
        ]

        for case in invalid_cases:
            match = pattern.match(case)
            assert match is None


class TestJSONFormatter:
    """Test JSONFormatter class"""

    @pytest.fixture
    def formatter(self) -> JSONFormatter:
        """Create a basic JSONFormatter instance"""
        return JSONFormatter()

    @pytest.fixture
    def custom_formatter(self) -> JSONFormatter:
        """Create a JSONFormatter with custom fmt_keys"""
        return JSONFormatter(fmt_keys={"level": "levelname", "msg": "message"})

    def test_init_default_values(self, formatter: JSONFormatter) -> None:
        """Test JSONFormatter initialization with default values"""
        assert formatter.fmt_keys == {}

    def test_init_with_fmt_keys(self, custom_formatter: JSONFormatter) -> None:
        """Test JSONFormatter initialization with custom fmt_keys"""
        assert custom_formatter.fmt_keys == {"level": "levelname", "msg": "message"}

    def test_init_with_none_fmt_keys(self) -> None:
        """Test JSONFormatter initialization with None fmt_keys"""
        formatter = JSONFormatter(fmt_keys=None)
        assert formatter.fmt_keys == {}

    def test_format_basic_record(self, formatter: JSONFormatter) -> None:
        """Test format method with basic LogRecord"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert data["message"] == "Test message"
        assert "timestamp" in data
        # Verify timestamp is in valid ISO format
        dt.datetime.fromisoformat(data["timestamp"])

    def test_format_record_with_args(self, formatter: JSONFormatter) -> None:
        """Test format method with LogRecord containing args"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message with %s and %d",
            args=("arg1", 42),
            exc_info=None,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert data["message"] == "Test message with arg1 and 42"

    def test_format_record_with_exception(self, formatter: JSONFormatter) -> None:
        """Test format method with LogRecord containing exception info"""
        try:
            error_message = "Test exception"
            raise ValueError(error_message)
        except ValueError:
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="/test/path.py",
            lineno=42,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        result = formatter.format(record)
        data = json.loads(result)

        assert data["message"] == "Error occurred"
        assert "exc_info" in data
        assert "ValueError: Test exception" in data["exc_info"]

    def test_format_record_with_stack_info(self, formatter: JSONFormatter) -> None:
        """Test format method with LogRecord containing stack info"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.stack_info = "Stack trace info"

        result = formatter.format(record)
        data = json.loads(result)

        assert data["message"] == "Test message"
        assert data["stack_info"] == "Stack trace info"

    def test_format_record_with_extra_fields(self, formatter: JSONFormatter) -> None:
        """Test format method with LogRecord containing extra fields"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        # Add extra fields
        record.user_id = "12345"  # pyre-ignore[16]
        record.request_id = "req-abc-123"  # pyre-ignore[16]
        record.custom_field = {"nested": "value"}  # pyre-ignore[16]

        result = formatter.format(record)
        data = json.loads(result)

        assert data["message"] == "Test message"
        assert data["user_id"] == "12345"
        assert data["request_id"] == "req-abc-123"
        assert data["custom_field"] == {"nested": "value"}

    def test_format_with_custom_fmt_keys(self, custom_formatter: JSONFormatter) -> None:
        """Test format method with custom fmt_keys"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = custom_formatter.format(record)
        data = json.loads(result)

        assert data["level"] == "INFO"
        assert data["msg"] == "Test message"
        assert data["message"] == "Test message"  # Always present

    def test_format_with_fmt_keys_missing_attribute(self) -> None:
        """Test format method with fmt_keys referencing a missing attribute"""
        formatter = JSONFormatter(fmt_keys={"missing": "nonexistent_attr"})
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        with pytest.raises(AttributeError):
            formatter.format(record)

    def test_prepare_log_dict_excludes_builtin_attrs(
        self, formatter: JSONFormatter
    ) -> None:
        """Test _prepare_log_dict excludes builtin attributes"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        # Add a custom attribute
        record.custom_attr = "custom_value"  # pyre-ignore[16]

        result = formatter.prepare_log_dict(record)

        assert result["custom_attr"] == "custom_value"
        assert "args" not in result  # Builtin attrs should be excluded
        assert "name" not in result  # Another builtin attr
        assert "message" in result  # Always present

    def test_prepare_log_dict_with_complex_objects(
        self, formatter: JSONFormatter
    ) -> None:
        """Test _prepare_log_dict with complex objects that need str() conversion"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        class CustomObject:
            def __str__(self) -> str:
                return "custom_object_str"

        custom_obj = CustomObject()
        record.custom_obj = custom_obj  # pyre-ignore[16]

        result = formatter.prepare_log_dict(record)

        assert result["custom_obj"] is custom_obj  # Object itself is stored

    def test_log_record_builtin_attrs_constant(self) -> None:
        """Test that LOG_RECORD_BUILTIN_ATTRS contains expected attributes"""
        expected_attrs = {
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

        assert expected_attrs == LOG_RECORD_BUILTIN_ATTRS

    @pytest.mark.parametrize(
        ("fmt_keys", "expected_keys"),
        [
            ({}, ["message", "timestamp"]),
            ({"level": "levelname"}, ["level", "message", "timestamp"]),
            (
                {"custom": "name", "level": "levelname"},
                ["custom", "level", "message", "timestamp"],
            ),
        ],
    )
    def test_format_with_various_fmt_keys(
        self, fmt_keys: dict[str, str], expected_keys: list[str]
    ) -> None:
        """Test format method with various fmt_keys configurations"""
        formatter = JSONFormatter(fmt_keys=fmt_keys)
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        result = formatter.format(record)
        data = json.loads(result)

        for key in expected_keys:
            assert key in data
