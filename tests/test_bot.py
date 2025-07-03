"""Unit tests for bot.py"""

import logging
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import Intents

from lib.bot import DiscordBot


def create_mock_user(name: str, user_id: int) -> MagicMock:
    """
    Helper function to create a mock discord.User
    with proper string representation
    """
    user = MagicMock(spec=discord.User)
    user.name = name
    user.id = user_id
    user.__str__ = MagicMock(return_value=name)
    return user


@pytest.fixture
def mock_bot_user() -> MagicMock:
    """Mock discord.User fixture for the bot"""
    return create_mock_user("TestBot", 12345)


@pytest.fixture
def mock_user() -> MagicMock:
    """Mock discord.User fixture for a non-bot user"""
    return create_mock_user("TestUser", 67890)


@pytest.fixture
def discord_bot(mock_bot_user: MagicMock) -> Iterator[DiscordBot]:
    """DiscordBot fixture with mocked user property"""
    intents: Intents = discord.Intents.default()
    bot = DiscordBot(intents=intents)

    with patch.object(type(bot), "user", mock_bot_user):
        yield bot


@pytest.fixture
def mock_channel() -> MagicMock:
    """Mock discord.abc.Messageable fixture"""
    channel = MagicMock(spec=discord.abc.Messageable)
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def mock_message(mock_user: MagicMock, mock_channel: MagicMock) -> MagicMock:
    """Mock discord.Message fixture"""
    message = MagicMock(spec=discord.Message)
    message.author = mock_user
    message.channel = mock_channel
    message.content = "test message"
    return message


class TestDiscordBot:
    """Test cases for DiscordBot class"""

    def test_inheritance(self, discord_bot: DiscordBot) -> None:
        """Test that DiscordBot inherits from discord.Client"""
        assert isinstance(discord_bot, discord.Client)

    async def test_on_ready(
        self,
        discord_bot: DiscordBot,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test the on_ready method logs correctly"""
        with caplog.at_level(logging.INFO):
            await discord_bot.on_ready()

        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "INFO"
        assert "We have logged in as TestBot" in caplog.records[0].message

    async def test_on_message_self_message_ignored(
        self, discord_bot: DiscordBot, mock_message: MagicMock
    ) -> None:
        """Test that messages from the bot itself are ignored"""
        mock_message.author = discord_bot.user

        await discord_bot.on_message(mock_message)

        mock_message.channel.send.assert_not_called()

    async def test_on_message_self_message_no_logging(
        self,
        discord_bot: DiscordBot,
        mock_message: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that self messages don't generate logs"""
        mock_message.author = discord_bot.user
        mock_message.content = "hello"

        with caplog.at_level(logging.INFO):
            await discord_bot.on_message(mock_message)

        assert len(caplog.records) == 0

    async def test_on_message_hello_response(
        self,
        discord_bot: DiscordBot,
        mock_user: MagicMock,
        mock_message: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that messages starting with 'hello' get a response"""
        mock_message.author = mock_user
        mock_message.content = "hello world"

        with caplog.at_level(logging.INFO):
            await discord_bot.on_message(mock_message)

        mock_message.channel.send.assert_called_once_with("Hello")
        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "INFO"
        assert "Received 'hello' from TestUser" in caplog.records[0].message

    @pytest.mark.parametrize(
        "message_content",
        [
            "hello",
            "Hello",
            "HELLO",
            "hello world",
            "Hello there!",
            "HELLO EVERYONE",
        ],
    )
    async def test_on_message_hello_case_insensitive(
        self,
        discord_bot: DiscordBot,
        mock_user: MagicMock,
        mock_message: MagicMock,
        message_content: str,
    ) -> None:
        """Test hello detection is case-insensitive"""
        mock_message.author = mock_user
        mock_message.content = message_content

        await discord_bot.on_message(mock_message)

        mock_message.channel.send.assert_called_once_with("Hello")

    @pytest.mark.parametrize(
        "message_content",
        [
            "hi there",
            "goodbye",
            "how are you",
            "help",
            "test message",
            "heloworld",
            "helo world",
        ],
    )
    async def test_on_message_no_hello_no_response(
        self,
        discord_bot: DiscordBot,
        mock_user: MagicMock,
        mock_message: MagicMock,
        message_content: str,
    ) -> None:
        """Test that messages not starting with 'hello' don't get a response"""
        mock_message.author = mock_user
        mock_message.content = message_content

        await discord_bot.on_message(mock_message)

        mock_message.channel.send.assert_not_called()

    async def test_on_message_hello_logging(
        self,
        discord_bot: DiscordBot,
        mock_user: MagicMock,
        mock_message: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that hello messages are logged correctly"""
        mock_message.author = mock_user
        mock_message.content = "hello bot"

        with caplog.at_level(logging.INFO):
            await discord_bot.on_message(mock_message)

        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"
        assert record.message == "Received 'hello' from TestUser"
        assert record.name == "lib.bot"

    async def test_on_message_not_hello_no_logging(
        self,
        discord_bot: DiscordBot,
        mock_user: MagicMock,
        mock_message: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that non-hello messages don't generate logs"""
        mock_message.author = mock_user
        mock_message.content = "goodbye"

        with caplog.at_level(logging.INFO):
            await discord_bot.on_message(mock_message)

        assert len(caplog.records) == 0
