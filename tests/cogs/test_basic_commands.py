"""Unit tests for the basic_commands.py"""

import importlib
import logging
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord.ext import commands

from lib.bot import DiscordBot
from lib.cogs.basic_commands import BasicCommands
from tests.utils import async_test


@pytest.fixture
def basic_commands_cog(discord_bot: DiscordBot) -> BasicCommands:
    """BasicCommands cog fixture"""
    return BasicCommands(discord_bot)


@pytest.fixture
def mock_context(mock_channel: MagicMock, mock_user: MagicMock) -> MagicMock:
    """Mock commands.Context fixture"""
    ctx = MagicMock(spec=commands.Context)
    ctx.author = mock_user
    ctx.channel = mock_channel
    ctx.send = AsyncMock()
    return ctx


class TestBasicCommands:
    """Test cases for the BasicCommands cog."""

    @async_test
    async def test_hello_command(
        self,
        caplog: pytest.LogCaptureFixture,
        basic_commands_cog: BasicCommands,
        mock_context: MagicMock,
    ) -> None:
        """Test the hello command responds correctly"""
        with caplog.at_level(logging.INFO):
            await basic_commands_cog.hello.callback(basic_commands_cog, mock_context)  # type: ignore[misc]

        mock_context.send.assert_called_once_with("Hello")
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"
        assert record.message == "Received 'hello' from TestUser"
        assert record.name == "lib.cogs.basic_commands"

    @async_test
    async def test_ping_command(
        self,
        caplog: pytest.LogCaptureFixture,
        basic_commands_cog: BasicCommands,
        mock_context: MagicMock,
    ) -> None:
        """Test the ping command responds correctly"""
        with caplog.at_level(logging.INFO):
            await basic_commands_cog.ping.callback(basic_commands_cog, mock_context)  # type: ignore[misc]

        mock_context.send.assert_called_once_with("Pong")
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"
        assert record.message == "Received 'ping' from TestUser"
        assert record.name == "lib.cogs.basic_commands"

    def test_cog_initialization(self, discord_bot: DiscordBot) -> None:
        """Test that the BasicCommands cog initializes correctly"""
        cog = BasicCommands(discord_bot)
        assert cog.bot is discord_bot
        assert isinstance(cog, commands.Cog)

    def test_type_checking_import_coverage(self) -> None:
        """Test to ensure TYPE_CHECKING import block is covered"""
        # Remove the module from sys.modules to force reimport
        module_name = "lib.cogs.basic_commands"
        if module_name in sys.modules:
            del sys.modules[module_name]

        # Mock TYPE_CHECKING to be True to force execution of the import block
        with patch("typing.TYPE_CHECKING", new=True):
            # Reimport the module which will now execute the TYPE_CHECKING block
            import lib.cogs.basic_commands  # noqa: PLC0415

            importlib.reload(lib.cogs.basic_commands)

        # Verify the module is properly loaded
        assert hasattr(lib.cogs.basic_commands, "BasicCommands")
