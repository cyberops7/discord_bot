"""Unit tests for api.py"""

import asyncio
import gc
from collections.abc import Generator
from contextlib import suppress
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

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
from tests.utils import async_test


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
def test_bot(mocker: MockerFixture, request: pytest.FixtureRequest) -> DiscordBot:
    """Fixture to mock the Discord bot instance"""
    bot = mocker.MagicMock(spec=DiscordBot)
    bot.latency = 0.123
    bot.is_ready.return_value = True

    user = getattr(request, "param", "TestBot#1234")

    if not user:
        bot.user = None
    else:
        user_mock = mocker.MagicMock(spec=ClientUser)
        user_mock.__str__ = mocker.MagicMock(return_value=user)
        bot.user = user_mock

    return cast("DiscordBot", bot)


@pytest.fixture
def test_api_app(test_bot: DiscordBot) -> FastAPI:
    app.state = AppState(bot=test_bot)
    return app


@pytest.fixture
def test_api_client(test_api_app: FastAPI) -> TestClient:
    return TestClient(test_api_app)


@async_test
async def test_lifespan_success(mocker: MockerFixture) -> None:
    """Test successful lifespan startup and shutdown"""
    mock_logger = mocker.patch("lib.api.logger")

    # Mock dependencies
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
    async with lifespan(
        mock_app
    ):  # pyrefly: ignore[missing-attribute] - Provided dynamically
        # Verify startup behavior
        mock_intents.all.assert_called_once()
        mock_discord_bot.assert_called_once_with(
            command_prefix="!", intents="mock_intents"
        )
        mock_bot.start.assert_called_once_with("test_token", reconnect=True)

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
    mocker: MockerFixture, mock_config: MagicMock
) -> None:
    """Test lifespan raises RuntimeError when BOT_TOKEN is not set"""
    mock_config.BOT_TOKEN = ""

    # Mock dependencies
    mock_logger = mocker.patch("lib.api.logger")

    mock_intents = mocker.patch("lib.api.Intents")
    mock_intents.all.return_value = "mock_intents"

    mock_bot = mocker.MagicMock(spec=DiscordBot)
    mock_discord_bot = mocker.patch("lib.api.DiscordBot", return_value=mock_bot)

    # Create a mock FastAPI app
    mock_app = mocker.MagicMock(spec=FastAPI)

    # Expect a RuntimeError when no BOT_TOKEN is provided
    with pytest.raises(RuntimeError, match=r"BOT_TOKEN is required to start the bot."):
        async with lifespan(
            mock_app
        ):  # pyrefly: ignore[missing-attribute] - Provided dynamically
            pass

    # Verify error logging
    mock_logger.error.assert_called_once_with("BOT_TOKEN is required to start the bot.")

    # Ensure initialization still happened
    mock_intents.all.assert_called_once()
    mock_discord_bot.assert_called_once_with(command_prefix="!", intents="mock_intents")


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

    mocker.patch("lib.api.asyncio.create_task", side_effect=asyncio.create_task)

    mock_logger = mocker.patch("lib.api.logger")

    # Create a mock FastAPI app
    mock_app: MagicMock = mocker.MagicMock(spec=FastAPI)
    mock_app.state = mocker.MagicMock()

    # Create a function that will raise the exception
    async def run_lifespan_with_exception() -> None:
        async with lifespan(
            mock_app
        ):  # pyrefly: ignore[missing-attribute] - Provided dynamically
            msg = "Test exception"
            raise ValueError(msg)

    # Simulate an exception during the yield lifecycle
    with pytest.raises(ValueError, match="Test exception"):
        await run_lifespan_with_exception()

    mock_bot.close.assert_called_once()
    mock_discord_bot.assert_called_once_with(command_prefix="!", intents="mock_intents")
    mock_bot.start.assert_called_once_with("test_token", reconnect=True)

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
