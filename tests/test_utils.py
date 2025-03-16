"""Unit testing for utils.py"""

import pytest
from pytest_mock import MockerFixture

from lib.utils import ensure_valid_port, validate_port


def test_ensure_valid_port_valid() -> None:
    assert ensure_valid_port(80) == 80
    assert ensure_valid_port(65535) == 65535
    assert ensure_valid_port(0) == 0
    assert ensure_valid_port(5555) == 5555


def test_ensure_valid_port_below_min() -> None:
    with pytest.raises(ValueError, match="Port -1 is not in the valid range 0-65535"):
        ensure_valid_port(-1)


def test_ensure_valid_port_above_max() -> None:
    with pytest.raises(
        ValueError, match="Port 65536 is not in the valid range 0-65535"
    ):
        ensure_valid_port(65536)


def test_ensure_valid_port_invalid_type() -> None:
    with pytest.raises(
        TypeError, match="Port must be an integer, but got str: invalid_port"
    ):
        ensure_valid_port("invalid_port")  # pyre-ignore[6]: Expected 'int', got 'str'
    with pytest.raises(TypeError, match="Port must be an integer, but got float: 50.5"):
        ensure_valid_port(50.5)  # pyre-ignore[6]: Expected 'int', got 'float'


def test_validate_port_valid() -> None:
    assert validate_port(80) == 80


def test_validate_port_invalid_type(mocker: MockerFixture) -> None:
    mock_exit = mocker.patch("sys.exit")
    mock_logger = mocker.patch("lib.utils.logger.exception")

    validate_port("cool port")  # pyre-ignore[6]: Expected 'int', got 'str'
    mock_exit.assert_called_once_with(1)
    mock_logger.assert_called_once_with(
        "Targeted port is not an integer: %s", "cool port"
    )


def test_validate_port_invalid_value(mocker: MockerFixture) -> None:
    mock_exit = mocker.patch("sys.exit")
    mock_logger = mocker.patch("lib.utils.logger.exception")

    validate_port(-10)
    mock_exit.assert_called_once_with(1)
    mock_logger.assert_called_once_with("Targeted port is not valid: %s", -10)
