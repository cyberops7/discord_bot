"""Unit tests for logger_setup.py"""

import logging
from logging.handlers import QueueListener
from typing import Any, cast
from unittest.mock import ANY, AsyncMock, MagicMock, Mock, NonCallableMagicMock

import pytest
import yaml
from pytest_mock import MockerFixture

from lib.logger_setup import (
    configure_logger,
    get_all_handlers,
    start_queue_listeners,
)


class MockQueueHandler(logging.Handler):
    def __init__(
        self,
        name: str,
        listener: QueueListener | Mock | None = None,
        level: int | str = 0,
    ) -> None:
        super().__init__(level)
        self.name = name
        self.listener = listener


@pytest.fixture
def mock_logger(
    mocker: MockerFixture,
) -> MagicMock | AsyncMock | NonCallableMagicMock:
    return mocker.patch("lib.logger_setup.logger")


@pytest.fixture
def mock_yaml_config() -> dict[
    str, int | dict[str, dict[str, str]] | dict[str, str | list[str]]
]:
    return {
        "version": 1,
        "formatters": {
            "simple": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "simple",
                "level": "DEBUG",
                "stream": "ext://sys.stdout",
            }
        },
        "root": {
            "level": "DEBUG",
            "handlers": ["console"],
        },
    }


def test_configure_logger(
    mocker: MockerFixture, mock_logger: MagicMock, mock_yaml_config: dict[str, Any]
) -> None:
    """
    Could actually write a file to disk for testing with:
        with open(yaml_file, "w") as f:
        yaml.dump(mock_yaml_config, f)
    """
    mock_path = mocker.patch("lib.logger_setup.Path", return_value=MagicMock())
    mocker.patch("yaml.safe_load", return_value=mock_yaml_config)

    configure_logger(".tmp/logger.yaml")

    expected_calls = [
        mocker.call.info("Loading logging configuration from YAML file..."),
        mocker.call.debug("Read YAML config: %s", mock_yaml_config),
        mocker.call.debug("Resolved YAML config: %s", mock_yaml_config),
        mocker.call.info("Logging configuration loaded from YAML file."),
        mocker.call.debug("Logging configuration: %s", mock_yaml_config),
        mocker.call.info("Checking for queue handler listeners..."),
    ]
    assert logging.root.level == logging.getLevelName(mock_yaml_config["root"]["level"])
    assert mock_logger.info.call_count == 3
    mock_logger.assert_has_calls(expected_calls, any_order=False)
    mock_path.assert_called_once()


@pytest.mark.parametrize(
    "exception",
    [
        FileNotFoundError,
        IsADirectoryError,
        OSError,
        PermissionError,
    ],
)
def test_configure_logger_outer_exceptions(
    mocker: MockerFixture, exception: type[Exception], mock_logger: MagicMock
) -> None:
    mock_path = mocker.patch("lib.logger_setup.Path", side_effect=exception)
    mock_basic_config = mocker.patch("lib.logger_setup.logging.basicConfig")

    configure_logger()

    expected_calls = [
        mocker.call.info("Loading logging configuration from YAML file..."),
        mocker.call.exception("Error reading logging configuration file."),
    ]
    mock_logger.assert_has_calls(expected_calls, any_order=False)
    mock_path.assert_called_once()
    mock_basic_config.assert_called_once()


def test_configure_logger_yaml_exception(
    mocker: MockerFixture, mock_logger: MagicMock
) -> None:
    mock_path = mocker.patch("lib.logger_setup.Path", return_value=MagicMock())
    mocker.patch("yaml.safe_load", side_effect=yaml.YAMLError)
    mock_basic_config = mocker.patch("logging.basicConfig")

    configure_logger(".tmp/bad_logger.yaml")

    expected_calls = [
        mocker.call.info("Loading logging configuration from YAML file..."),
        mocker.call.exception("Error parsing YAML file."),
        mocker.call.info("Default logging configuration applied."),
    ]
    mock_logger.assert_has_calls(expected_calls, any_order=False)
    mock_path.assert_called_once()
    mock_basic_config.assert_called_once()


@pytest.mark.parametrize(
    "exception",
    [
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
    ],
)
def test_configure_logger_inner_exceptions(
    mocker: MockerFixture,
    mock_logger: MagicMock,
    mock_yaml_config: dict[str, Any],
    exception: type[Exception],
) -> None:
    mock_path = mocker.patch("pathlib.Path.open", return_value=MagicMock())
    mocker.patch("yaml.safe_load", return_value=mock_yaml_config)
    mocker.patch("logging.config.dictConfig", side_effect=exception)
    mock_basic_config = mocker.patch("logging.basicConfig")

    configure_logger()

    expected_calls = [
        mocker.call.info("Loading logging configuration from YAML file..."),
        mocker.call.debug("Read YAML config: %s", mock_yaml_config),
        mocker.call.debug("Resolved YAML config: %s", mock_yaml_config),
        mocker.call.exception("Error in logging configuration."),
        mocker.call.info("Default logging configuration applied."),
    ]
    mock_logger.assert_has_calls(expected_calls, any_order=False)
    mock_path.assert_called_once()
    mock_basic_config.assert_called_once()


def test_get_all_handlers() -> None:
    logging.basicConfig()
    handlers = get_all_handlers()
    assert isinstance(handlers, set)
    assert isinstance(handlers.pop(), logging.Handler)


def test_start_queue_listeners(mocker: MockerFixture, mock_logger: MagicMock) -> None:
    mocked_queue_handler = MockQueueHandler(
        name="queue_handler", listener=mocker.Mock()
    )
    mock_get_all_handlers = mocker.patch(
        "lib.logger_setup.get_all_handlers", return_value={mocked_queue_handler}
    )

    start_queue_listeners()

    expected_calls = [
        mocker.call.info("Checking for queue handler listeners..."),
        mocker.call.info("Found queue handler: %s", mocked_queue_handler.name),
        mocker.call.info(
            "Starting listener for handler: %s", mocked_queue_handler.name
        ),
    ]
    mock_logger.assert_has_calls(expected_calls, any_order=False)
    mock_get_all_handlers.assert_called_once()
    if mocked_queue_handler.listener is not None:
        listener = cast("Mock", mocked_queue_handler.listener)
        listener.start.assert_called_once()
        listener.stop.assert_not_called()


def test_start_queue_listeners_no_queue_handlers(
    mocker: MockerFixture, mock_logger: MagicMock
) -> None:
    mock_get_all_handlers = mocker.patch(
        "lib.logger_setup.get_all_handlers", return_value={}
    )

    start_queue_listeners()

    expected_calls = [
        mocker.call.info("Checking for queue handler listeners..."),
        mocker.call.warning("No handlers found."),
    ]
    mock_logger.assert_has_calls(expected_calls, any_order=False)
    mock_get_all_handlers.assert_called_once()


def test_start_queue_listeners_callable_handler(
    mocker: MockerFixture, mock_logger: MagicMock
) -> None:
    """Test start_queue_listeners when 'handler_name' is callable (e.g., weakref)"""
    mocked_queue_handler = MockQueueHandler(
        name="queue_handler", listener=mocker.Mock()
    )
    callable_handler = mocker.Mock(return_value=mocked_queue_handler)
    mock_get_all_handlers = mocker.patch(
        "lib.logger_setup.get_all_handlers", return_value={callable_handler}
    )

    start_queue_listeners()

    expected_calls = [
        mocker.call.info("Checking for queue handler listeners..."),
        mocker.call.info("Found queue handler: %s", mocked_queue_handler.name),
        mocker.call.info(
            "Starting listener for handler: %s", mocked_queue_handler.name
        ),
    ]
    mock_logger.assert_has_calls(expected_calls, any_order=False)
    mock_get_all_handlers.assert_called_once()
    callable_handler.assert_called_once()  # Verify the callable was invoked
    if mocked_queue_handler.listener is not None:
        listener = cast("Mock", mocked_queue_handler.listener)
        listener.start.assert_called_once()
        listener.stop.assert_not_called()


def test_start_queue_listeners_invalid_handler_type(
    mocker: MockerFixture, mock_logger: MagicMock
) -> None:
    """Test start_queue_listeners when 'handler' is not a logging.Handler instance"""
    # Create a mock object that is not a logging.Handler
    invalid_handler = mocker.Mock()
    invalid_handler.__class__ = str  # Make it clearly not a Handler
    mock_get_all_handlers = mocker.patch(
        "lib.logger_setup.get_all_handlers", return_value={invalid_handler}
    )

    start_queue_listeners()

    expected_calls = [
        mocker.call.info("Checking for queue handler listeners..."),
        mocker.call.warning("Invalid handler type: %s", ANY),
    ]
    mock_logger.assert_has_calls(expected_calls, any_order=False)
    mock_get_all_handlers.assert_called_once()
    assert mock_logger.warning.call_args[0][1].__name__ == "Mock"


@pytest.mark.parametrize(
    ("exception", "expected_message"),
    [
        (
            ReferenceError("weak reference expired"),
            "Weak reference expired for handler %s: %s",
        ),
        (TypeError("type error occurred"), "Type error when processing handler %s: %s"),
    ],
)
def test_start_queue_listeners_handler_exceptions(
    mocker: MockerFixture,
    mock_logger: MagicMock,
    exception: Exception,
    expected_message: str,
) -> None:
    """
    Test start_queue_listeners when handler processing raises
    ReferenceError or TypeError
    """
    faulty_handler = mocker.Mock(side_effect=exception)
    mock_get_all_handlers = mocker.patch(
        "lib.logger_setup.get_all_handlers", return_value={faulty_handler}
    )

    start_queue_listeners()

    expected_calls = [
        mocker.call.info("Checking for queue handler listeners..."),
        mocker.call.warning(expected_message, faulty_handler, exception),
    ]
    mock_logger.assert_has_calls(expected_calls, any_order=False)
    mock_get_all_handlers.assert_called_once()


def test_start_queue_listeners_no_listener(
    mocker: MockerFixture, mock_logger: MagicMock
) -> None:
    """Test start_queue_listeners when 'queue handler' has no listener"""
    # Create a queue handler without a listener (listener=None)
    mocked_queue_handler = MockQueueHandler(name="queue_handler", listener=None)
    mock_get_all_handlers = mocker.patch(
        "lib.logger_setup.get_all_handlers", return_value={mocked_queue_handler}
    )

    start_queue_listeners()

    expected_calls = [
        mocker.call.info("Checking for queue handler listeners..."),
        mocker.call.info("Found queue handler: %s", mocked_queue_handler.name),
        mocker.call.warning(
            "No listener found for handler: %s", mocked_queue_handler.name
        ),
    ]
    mock_logger.assert_has_calls(expected_calls, any_order=False)
    mock_get_all_handlers.assert_called_once()
