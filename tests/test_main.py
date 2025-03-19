"""Unit tests for main.py"""

import asyncio
import contextlib
import os
from collections.abc import Iterator
from unittest.mock import AsyncMock, Mock

import pytest
from pytest_mock import MockerFixture

from lib.bot import DiscordBot
from main import main


@pytest.fixture(autouse=True)
def set_env_vars() -> Iterator[None]:
    original_env = os.environ.copy()
    os.environ["BOT_TOKEN"] = "fake-token"  # noqa: S105
    os.environ["API_PORT"] = "8000"
    yield
    os.environ.clear()
    os.environ.update(original_env)


@pytest.mark.asyncio  # pyre-ignore[56]: cannot infer type of decorator
async def test_main_successful_run(mocker: MockerFixture) -> None:
    mocker.patch("main.load_dotenv")
    mocker.patch("main.configure_logger")
    mocker.patch("main.validate_port", return_value=8000)

    mock_logger: Mock = mocker.patch("main.logger")
    mock_start_fastapi_server: Mock = mocker.patch("main.start_fastapi_server")

    mock_bot_instance: Mock = mocker.Mock(spec=["start"])

    async def mock_bot_start(token: str) -> None:  # noqa: ARG001
        await asyncio.sleep(0.1)
        raise asyncio.CancelledError

    mock_bot_instance.start = AsyncMock(side_effect=mock_bot_start)
    mocker.patch("main.DiscordBot", return_value=mock_bot_instance)

    await main()

    mock_start_fastapi_server.assert_called_once_with(bot=mock_bot_instance, port=8000)
    mock_bot_instance.start.assert_awaited_once_with("fake-token")

    expected_calls = [
        mocker.call.info("Retrieving bot token..."),
        mocker.call.info("Initializing bot..."),
        mocker.call.info("Starting FastAPI server..."),
        mocker.call.info("Starting Discord bot..."),
        mocker.call.info("FastAPI server task cancelled."),
    ]
    assert mock_logger.info.call_count == len(expected_calls)
    mock_logger.assert_has_calls(expected_calls, any_order=False)


@pytest.mark.asyncio  # pyre-ignore[56]: cannot infer type of decorator
async def test_main_bot_token_not_set(mocker: MockerFixture) -> None:
    mocker.patch("main.load_dotenv")
    mocker.patch("main.configure_logger")
    mock_logger: Mock = mocker.patch("main.logger")

    os.environ.pop("BOT_TOKEN", None)

    with pytest.raises(SystemExit) as exc:
        await main()

    expected_calls = [
        mocker.call.info("Retrieving bot token..."),
        mocker.call.error("BOT_TOKEN is not set"),
    ]
    assert exc.value.code == 1
    mock_logger.assert_has_calls(expected_calls, any_order=False)


@pytest.mark.asyncio  # pyre-ignore[56]: cannot infer type of decorator
async def test_main_keyboard_interrupt(mocker: MockerFixture) -> None:
    mocker.patch("main.load_dotenv")
    mocker.patch("main.configure_logger")
    mocker.patch("main.validate_port", return_value=8000)
    mocker.patch("main.start_fastapi_server")

    mock_logger: Mock = mocker.patch("main.logger")

    mock_bot_instance: Mock = mocker.Mock(spec=["start"])
    mock_bot_instance.start = AsyncMock(side_effect=KeyboardInterrupt)
    mocker.patch("main.DiscordBot", return_value=mock_bot_instance)

    with pytest.raises(KeyboardInterrupt):
        await main()

    expected_calls = [
        mocker.call.info("Retrieving bot token..."),
        mocker.call.info("Initializing bot..."),
        mocker.call.info("Starting FastAPI server..."),
        mocker.call.info("Starting Discord bot..."),
        mocker.call.info("Shutting down gracefully..."),
        mocker.call.info("FastAPI server task cancelled during cleanup."),
    ]
    assert mock_logger.info.call_count == len(expected_calls)
    mock_logger.assert_has_calls(expected_calls, any_order=False)


@pytest.mark.asyncio  # pyre-ignore[56]: cannot infer type of decorator
async def test_main_fastapi_server_task_cancelled(mocker: MockerFixture) -> None:
    mocker.patch("main.load_dotenv")
    mocker.patch("main.configure_logger")
    mocker.patch("main.validate_port", return_value=8000)

    # Mock start_fastapi_server coroutine to wait indefinitely until cancelled
    async def mock_start_fastapi(bot: DiscordBot, port: int) -> None:  # noqa: ARG001
        # allow cancel to cleanly exit, just like real coroutine
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.Event().wait()  # indefinite wait

    mocker.patch("main.start_fastapi_server", side_effect=mock_start_fastapi)

    # Mock bot.start to immediately finish
    mock_bot_instance: Mock = mocker.Mock(spec=["start"])
    mock_bot_instance.start = AsyncMock(return_value=None)
    mocker.patch("main.DiscordBot", return_value=mock_bot_instance)

    # Patch logger carefully
    mock_logger = mocker.patch("main.logger")

    # Actually run main()
    await main()

    expected_calls = [
        mocker.call.info("Retrieving bot token..."),
        mocker.call.info("Initializing bot..."),
        mocker.call.info("Starting FastAPI server..."),
        mocker.call.info("Starting Discord bot..."),
        mocker.call.info(
            "FastAPI server task cancelled during cleanup."
        ),  # confirms task cancellation explicitly via logs
    ]
    assert mock_logger.info.call_count == len(expected_calls)
    mock_logger.assert_has_calls(expected_calls, any_order=False)
