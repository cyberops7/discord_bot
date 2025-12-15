"""Unit testing for utils.py"""

import pytest
from pytest_mock import MockerFixture

from lib.utils import ensure_valid_port, validate_port


@pytest.mark.parametrize(
    "port",
    [
        0,
        80,
        5555,
        65535,
    ],
)
def test_ensure_valid_port_valid(port: int) -> None:
    assert ensure_valid_port(port) == port


@pytest.mark.parametrize(
    "port",
    [
        -1,
        65536,
    ],
)
def test_ensure_valid_port_out_of_range(port: int) -> None:
    with pytest.raises(
        ValueError, match=f"Port {port} is not in the valid range 0-65535"
    ):
        ensure_valid_port(port)


def test_ensure_valid_port_above_max() -> None:
    with pytest.raises(
        ValueError, match="Port 65536 is not in the valid range 0-65535"
    ):
        ensure_valid_port(65536)


@pytest.mark.parametrize(
    "invalid_port",
    [
        "I'm a string",
        50.5,
    ],
)
def test_ensure_valid_port_invalid_type(invalid_port: str | float) -> None:
    with pytest.raises(
        TypeError,
        match=f"Port must be an integer, but got "
        f"{type(invalid_port).__name__}: {invalid_port}",
    ):
        # noinspection PyTypeChecker
        # pyrefly: ignore[bad-argument-type]
        ensure_valid_port(invalid_port)


def test_validate_port_valid(mocker: MockerFixture) -> None:
    mocker.patch("lib.utils.ensure_valid_port", return_value=80)
    assert validate_port(80) == 80


def test_validate_port_invalid_type(mocker: MockerFixture) -> None:
    bad_port = "cool port"
    mock_exit = mocker.patch("sys.exit")
    mock_logger = mocker.patch("lib.utils.logger")

    # noinspection PyTypeChecker
    # pyrefly: ignore[bad-argument-type]
    validate_port(bad_port)
    mock_exit.assert_called_once_with(1)
    expected_logs = [
        mocker.call.debug("Validating targeted port: %s...", bad_port),
        mocker.call.exception("Targeted port is not an integer: %s", bad_port),
        mocker.call.error("Exiting due to invalid port."),
    ]
    mock_logger.assert_has_calls(expected_logs, any_order=False)


def test_validate_port_invalid_value(mocker: MockerFixture) -> None:
    mock_exit = mocker.patch("sys.exit")
    mock_logger = mocker.patch("lib.utils.logger.exception")

    validate_port(-10)
    mock_exit.assert_called_once_with(1)
    mock_logger.assert_called_once_with("Targeted port is not valid: %s", -10)
