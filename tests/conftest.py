"""Pytest fixtures"""

import datetime
from collections.abc import Generator, Iterator
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
    user = MagicMock(spec=discord.Member)
    user.display_name = name
    user.name = name
    user.id = user_id
    user.mention = f"<@{user_id}>"
    user.roles = []  # Set the role(s) as necessary in each test
    user.send = AsyncMock()
    user.__str__ = MagicMock(return_value=name)
    return user


@pytest.fixture
def mock_bot_user() -> MagicMock:
    """Mock discord.User fixture for the bot"""
    return create_mock_user("TestBot", 12345)


@pytest.fixture
def mock_mod() -> MagicMock:
    """Mock discord.User fixture for a moderator"""
    return create_mock_user("TestMod", 54321)


@pytest.fixture
def mock_user() -> MagicMock:
    """Mock discord.User fixture for a non-bot user"""
    return create_mock_user("TestUser", 67890)


@pytest.fixture
def discord_bot(mock_bot_user: MagicMock) -> Iterator[DiscordBot]:
    """DiscordBot fixture with mocked user property"""
    intents: Intents = discord.Intents.default()
    bot = DiscordBot(command_prefix="!", intents=intents)

    with patch.object(type(bot), "user", mock_bot_user):
        yield bot


@pytest.fixture
def mock_channel(channel_id: int = 999) -> MagicMock:
    """Mock discord.abc.Messageable fixture"""
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id
    channel.mention = f"<#{channel_id}>"
    channel.name = "test-channel"
    channel.send = AsyncMock()
    return channel


@pytest.fixture(autouse=True)
def mock_config(
    request: pytest.FixtureRequest, mock_channel: MagicMock
) -> Generator[MagicMock, None, None]:  # noqa: UP043 unnecessary default type args
    """Mock the config object for all imports"""
    # Bypass the fixture if the test is marked with @pytest.mark.no_mock_config
    if "no_mock_config" in request.keywords:
        yield MagicMock()
        return

    # Create the base mock config first
    with patch("lib.config.config") as mock_cfg:
        # Set up all the config attributes before applying patches that trigger imports
        mock_cfg.CHANNELS.BOT_LOGS = 101
        mock_cfg.CHANNELS.BOT_PLAYGROUND = 123
        mock_cfg.CHANNELS.MOUSETRAP = 456
        mock_cfg.CHANNELS.RULES = 789
        mock_cfg.LOG_CHANNEL = mock_channel(channel_id=mock_cfg.CHANNELS.BOT_LOGS)
        mock_cfg.LOG_CHANNEL.send = AsyncMock()
        mock_cfg.ROLES.ADMIN = 11111
        mock_cfg.ROLES.JIMS_GARAGE = 22222
        mock_cfg.ROLES.MOD = 33333
        mock_cfg.ROLES.BOTS = 44444
        mock_cfg.ROLES.GARAGE_MEMBER = 55555
        mock_cfg.GUILDS.JIMS_GARAGE = 66666
        mock_cfg.TIMEZONE = datetime.UTC

        # Now apply the remaining patches that might trigger module imports
        with (
            patch("lib.bot.config", mock_cfg),
            patch("lib.bot_log_context.config", mock_cfg),
            patch("lib.cogs.tasks.config", mock_cfg),
        ):
            yield mock_cfg


@pytest.fixture
def mock_guild(mock_config: MagicMock) -> MagicMock:
    """Mock discord.Guild fixture"""
    guild = MagicMock(spec=discord.Guild)
    guild.id = mock_config.GUILDS.JIMS_GARAGE
    guild.name = "Test Guild"
    guild.members = []
    return guild


@pytest.fixture
def mock_message(mock_user: MagicMock, mock_channel: MagicMock) -> MagicMock:
    """Mock discord.Message fixture"""
    message = MagicMock(spec=discord.Message)
    message.author = mock_user
    message.channel = mock_channel
    message.content = "test message"
    return message
