"""Unit tests for api.py"""

from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from unittest.mock import MagicMock

import pytest
import uvicorn
from discord import ClientUser
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest_mock import MockerFixture

from lib.api import (
    AppState,
    HealthCheckResponse,
    StatusResponse,
    app,
    start_fastapi_server,
)
from lib.bot import DiscordBot


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


@pytest.mark.asyncio  # pyre-ignore[56]: cannot infer type of decorator
async def test_start_fastapi_server(
    mocker: MockerFixture, test_bot: DiscordBot
) -> None:
    mock_server = mocker.patch.object(
        uvicorn.Server, "serve", new_callable=mocker.AsyncMock
    )

    await start_fastapi_server(test_bot, port=8000)

    mock_server.assert_awaited_once()


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
