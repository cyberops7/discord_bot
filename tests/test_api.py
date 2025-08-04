"""Unit tests for api.py"""

import asyncio
import builtins
import gc
from collections.abc import Callable, Generator
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

if TYPE_CHECKING:
    from unittest.mock import MagicMock

import pytest
from discord import ClientUser
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from lib.api import (
    AppState,
    HealthCheckResponse,
    StatusResponse,
    app,
    lifespan,
)
from lib.bot import DiscordBot
from lib.utils import async_test


@pytest.fixture(autouse=True)
def finalize_mocks() -> Generator[None, None, None]:  # noqa: UP043
    """Ensure that no mocked async methods are left unawaited."""
    yield
    # Finalize any residual asyncio mocks or coroutines
    for obj in gc.get_objects():
        if isinstance(obj, AsyncMock) and obj.await_count == 0:
            with suppress(RuntimeError):  # Ignore if an event loop is already closed
                asyncio.run(obj())


@pytest.fixture
def mock_os_getenv(mocker: MockerFixture) -> Callable[[str, str | None], Mock]:
    """Fixture to mock lib.api.os.getenv for specific keys."""

    def apply_patch(key: str, value: str | None) -> Mock:
        original_getenv = builtins.__import__(
            "os"
        ).getenv  # Access the original without being mocked
        patch = mocker.patch("lib.api.os.getenv", autospec=True)
        patch.side_effect = (
            lambda k, default=None: value if k == key else original_getenv(k, default)
        )
        return patch

    return apply_patch


@pytest.fixture
def test_bot(mocker: MockerFixture, request: pytest.FixtureRequest) -> DiscordBot:
    """Fixture to mock the Discord bot instance"""
    bot = mocker.MagicMock(spec=DiscordBot)
    bot.latency = 0.123
    bot.is_ready.return_value = True

    user = getattr(request, "param", "TestBot#1234")

    if not user:
        bot.user = None
    else:
        bot.user = mocker.MagicMock(spec=ClientUser)
        bot.user.__str__.return_value = user

    return cast("DiscordBot", bot)


@pytest.fixture
def test_api_app(test_bot: DiscordBot) -> FastAPI:
    app.state = AppState(bot=test_bot)
    return app


@pytest.fixture
def test_api_client(test_api_app: FastAPI) -> TestClient:
    return TestClient(test_api_app)


@async_test
async def test_lifespan_success(
    mocker: MockerFixture, mock_os_getenv: Callable[[str, str | None], Mock]
) -> None:
    """Test successful lifespan startup and shutdown"""
    mock_logger = mocker.patch("lib.api.logger")

    # Mock dependencies
    mock_getenv = mock_os_getenv("BOT_TOKEN", "test_token")
    mock_intents = mocker.patch("lib.api.Intents")
    mock_intents.all.return_value = "mock_intents"

    # Mock the DiscordBot and its methods
    mock_bot = mocker.MagicMock(spec=DiscordBot)
    mock_bot.start = AsyncMock()
    mock_bot.close = AsyncMock()
    mock_discord_bot = mocker.patch("lib.api.DiscordBot", return_value=mock_bot)

    mocker.patch("lib.api.asyncio.create_task", side_effect=asyncio.create_task)

    # Create a mock FastAPI app
    mock_app = mocker.MagicMock(spec=FastAPI)
    mock_app.state = mocker.MagicMock()

    # Use the lifespan context manager
    async with lifespan(mock_app):  # pyre-ignore[16] - Provided dynamically
        # Verify startup behavior
        mock_intents.all.assert_called_once()
        mock_discord_bot.assert_called_once_with(intents="mock_intents")
        mock_getenv.assert_called_once_with("BOT_TOKEN")
        mock_bot.start.assert_called_once_with("test_token")

        # Verify bot is assigned to FastAPI state
        assert mock_app.state.bot == mock_bot

    # Verify shutdown behavior
    mock_bot.close.assert_called_once()

    # Ensure the logs were created in the right order
    expected_logs = [
        mocker.call.info("Initializing Discord bot..."),
        mocker.call.info("Retrieving bot token..."),
        mocker.call.info("Starting Discord bot..."),
        mocker.call.info("Shutting down Discord bot..."),
        mocker.call.info("Discord bot closed."),
    ]
    mock_logger.info.assert_has_calls(expected_logs, any_order=False)


@async_test
async def test_lifespan_no_bot_token(
    mocker: MockerFixture, mock_os_getenv: Callable[[str, str | None], Mock]
) -> None:
    """Test lifespan raises RuntimeError when BOT_TOKEN is not set"""
    # Mock only "BOT_TOKEN" to return "test_token"
    mock_getenv = mock_os_getenv("BOT_TOKEN", None)

    # Mock dependencies
    mock_logger = mocker.patch("lib.api.logger")

    mock_intents = mocker.patch("lib.api.Intents")
    mock_intents.all.return_value = "mock_intents"

    mock_bot = mocker.MagicMock(spec=DiscordBot)
    mock_discord_bot = mocker.patch("lib.api.DiscordBot", return_value=mock_bot)

    # Create a mock FastAPI app
    mock_app = mocker.MagicMock(spec=FastAPI)

    # Expect a RuntimeError when no BOT_TOKEN is provided
    with pytest.raises(RuntimeError, match="BOT_TOKEN is required to start the bot."):
        async with lifespan(mock_app):  # pyre-ignore[16] - Provided dynamically
            pass

    # Verify error logging
    mock_logger.error.assert_called_once_with("BOT_TOKEN is required to start the bot.")

    # Ensure initialization still happened
    mock_intents.all.assert_called_once()
    mock_discord_bot.assert_called_once_with(intents="mock_intents")
    mock_getenv.assert_called_once_with("BOT_TOKEN")


@async_test
async def test_lifespan_cleanup_on_exception(mocker: MockerFixture) -> None:
    """Test that bot cleanup happens even if an exception occurs during the lifespan"""
    # Mock dependencies
    mock_intents = mocker.patch("lib.api.Intents")
    mock_intents.all.return_value = "mock_intents"

    mock_bot = mocker.MagicMock(spec=DiscordBot)
    mock_bot.start = AsyncMock()
    mock_bot.close = AsyncMock()
    mock_discord_bot = mocker.patch("lib.api.DiscordBot", return_value=mock_bot)

    # Mock environment variable for BOT_TOKEN
    # A more complicated patch, so we don't mess up pytest loading its own env vars
    mock_getenv = mocker.patch("lib.api.os.getenv")
    mock_getenv.configure_mock(
        side_effect=lambda key, default=None: "test_token"
        if key == "BOT_TOKEN"
        else default,
    )

    mocker.patch("lib.api.asyncio.create_task", side_effect=asyncio.create_task)

    mock_logger = mocker.patch("lib.api.logger")

    # Create a mock FastAPI app
    mock_app: MagicMock = mocker.MagicMock(spec=FastAPI)
    mock_app.state = mocker.MagicMock()

    # Create a function that will raise the exception
    async def run_lifespan_with_exception() -> None:
        async with lifespan(mock_app):  # pyre-ignore[16] - Provided dynamically
            msg = "Test exception"
            raise ValueError(msg)

    # Simulate an exception during the yield lifecycle
    with pytest.raises(ValueError, match="Test exception"):
        await run_lifespan_with_exception()

    mock_bot.close.assert_called_once()
    mock_discord_bot.assert_called_once_with(intents="mock_intents")
    mock_getenv.assert_called_once_with("BOT_TOKEN")
    mock_bot.start.assert_called_once_with("test_token")

    expected_logs = [
        mocker.call.info("Initializing Discord bot..."),
        mocker.call.info("Retrieving bot token..."),
        mocker.call.info("Starting Discord bot..."),
        mocker.call.info("Shutting down Discord bot..."),
        mocker.call.info("Discord bot closed."),
    ]
    mock_logger.assert_has_calls(expected_logs, any_order=False)


def test_route_favicon(test_api_client: TestClient, mocker: MockerFixture) -> None:
    mock_file_response = mocker.patch(
        "lib.api.FileResponse", return_value="fake-favicon-response"
    )

    response = test_api_client.get("/favicon.ico")

    assert response.status_code == 200
    mock_file_response.assert_called_once_with(Path("static/favicon.ico"))


@pytest.mark.parametrize(
    ("bot_ready", "expected_status", "expected_message", "status_code"),
    [
        (True, "ok", "Bot is running and ready", 200),
        (False, "not_ready", "Bot is not ready", 503),
    ],
)
def test_route_healthcheck(
    test_api_client: TestClient,
    test_bot: DiscordBot,
    bot_ready: bool,
    expected_status: str,
    expected_message: str,
    status_code: int,
) -> None:
    test_bot_mock: MagicMock = cast("MagicMock", test_bot)
    test_bot_mock.is_ready.return_value = bot_ready
    response = test_api_client.get("/healthcheck")

    response_json = response.json()
    assert response.status_code == status_code
    assert (
        response_json
        == HealthCheckResponse(
            status=expected_status,
            message=expected_message,
        ).model_dump()
    )


@pytest.mark.parametrize(
    ("test_bot", "expected_user"),
    [
        ("TestBot#1234", "TestBot#1234"),
        (None, "Unknown"),
    ],
    indirect=["test_bot"],
)
def test_route_status(
    test_api_client: TestClient, test_bot: DiscordBot, expected_user: str
) -> None:
    response = test_api_client.get("/status")

    expected_response = StatusResponse(
        latency=test_bot.latency,
        is_ready=True,
        user=expected_user,
    )

    assert response.status_code == 200
    response_json = response.json()
    assert response_json == expected_response.model_dump()
