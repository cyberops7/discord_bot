"""Unit tests for main.py"""

import os
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, Mock, NonCallableMagicMock

import pytest
from pytest_mock import MockerFixture

from main import main


@pytest.fixture(autouse=True)
def mock_common_calls(
    mocker: MockerFixture,
) -> tuple[
    MagicMock | AsyncMock | NonCallableMagicMock,
    MagicMock | AsyncMock | NonCallableMagicMock,
]:
    """Fixture to mock common calls"""
    mock_load_dotenv = mocker.patch("main.load_dotenv")
    mock_configure_logger = mocker.patch("main.configure_logger")
    return mock_load_dotenv, mock_configure_logger


@pytest.fixture(autouse=True)
def set_env_vars() -> Iterator[None]:
    """Fixture to set environment variables for all tests"""
    original_env = os.environ.copy()
    os.environ["API_PORT"] = "8000"
    yield
    os.environ.clear()
    os.environ.update(original_env)


@pytest.fixture
def mock_logger(mocker: MockerFixture) -> Mock:
    """Fixture to mock the logger"""
    return mocker.patch("main.logger")


@pytest.fixture
def mock_uvicorn(mocker: MockerFixture) -> Mock:
    """Fixture to mock uvicorn.run"""
    return mocker.patch("main.uvicorn.run")


def test_main_successful_run(
    mocker: MockerFixture,
    mock_common_calls: tuple[Mock, Mock],
    mock_logger: Mock,
    mock_uvicorn: Mock,
) -> None:
    """Test successful execution of main()"""
    # Unpack the mocks directly from the fixture in the function signature
    mock_load_dotenv, mock_configure_logger = mock_common_calls

    # Mock validate_port to return a specific value
    mocker.patch("main.validate_port", return_value=8000)

    # Call the main function
    main()

    # Verify expected log messages
    expected_logs = [
        mocker.call.info(
            "Loading environment variables from .env file (if present)..."
        ),
        mocker.call.info("Configuring logger..."),
        mocker.call.info("Starting FastAPI server..."),
    ]
    mock_logger.assert_has_calls(expected_logs, any_order=False)

    # Verify that uvicorn.run was called with the correct parameters
    mock_uvicorn.assert_called_once_with(
        mocker.ANY,  # app
        host="0.0.0.0",  # noqa: S104
        port=8000,
        log_config=None,
    )

    mock_load_dotenv.assert_called_once_with(override=True)
    mock_configure_logger.assert_called_once()


def test_default_port(mocker: MockerFixture, mock_uvicorn: Mock) -> None:
    """Test that the default port is used when API_PORT is not set"""
    # Remove API_PORT from environment
    os.environ.pop("API_PORT", None)

    # Mock validate_port to return the default port
    mock_validate_port = mocker.patch("main.validate_port", return_value=8080)

    # Call the main function
    main()

    # Verify that validate_port was called with the default port
    mock_validate_port.assert_called_once_with(8080)

    # Verify that uvicorn.run was called with the default port
    mock_uvicorn.assert_called_once_with(
        mocker.ANY,
        host="0.0.0.0",  # noqa: S104
        port=8080,
        log_config=None,
    )


def test_invalid_port() -> None:
    """Test behavior with invalid port values"""
    # Set an invalid port in the environment
    os.environ["API_PORT"] = "invalid"

    # Call the main function and expect ValueError to be raised
    # since main.py tries to convert API_PORT to int
    with pytest.raises(
        ValueError, match=r"invalid literal for int\(\) with base 10: \'invalid\'"
    ):
        main()
