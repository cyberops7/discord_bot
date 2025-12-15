"""Unit tests for the basic_commands.py"""

import datetime
import importlib
import logging
import sys
import time
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import discord
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


@pytest.fixture
def mock_interaction(mock_channel: MagicMock, mock_user: MagicMock) -> MagicMock:
    """Mock discord.Interaction fixture"""
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = mock_user
    interaction.channel = mock_channel
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    interaction.created_at = datetime.datetime.now(datetime.UTC)
    return interaction


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

    @async_test
    async def test_slash_hello_command(
        self,
        caplog: pytest.LogCaptureFixture,
        basic_commands_cog: BasicCommands,
        mock_interaction: MagicMock,
    ) -> None:
        """Test the slash hello command responds correctly"""
        with caplog.at_level(logging.INFO):
            await basic_commands_cog.slash_hello.callback(
                basic_commands_cog,  # pyrefly: ignore[bad-argument-type]
                mock_interaction,  # pyrefly: ignore[bad-argument-count]
            )

        mock_interaction.response.send_message.assert_called_once_with("Hello world.")
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"
        assert (
            record.message == f"Received slash 'hello' from TestUser in channel "
            f"{mock_interaction.channel}"
        )
        assert record.name == "lib.cogs.basic_commands"

    @pytest.mark.parametrize(
        (
            "ws_latency_seconds",
            "expected_ws_status",
            "api_latency_seconds",
            "expected_api_status",
        ),
        [
            # Test all WebSocket latency qualities with various API latencies
            (0.05, "Excellent", 0.1, "Excellent"),  # 50 ms WS, 100 ms API
            (0.05, "Excellent", 0.2, "Good"),  # 50 ms WS, 200 ms API
            (0.05, "Excellent", 0.4, "Fair"),  # 50 ms WS, 400 ms API
            (0.05, "Excellent", 0.7, "Poor"),  # 50 ms WS, 700 ms API
            (0.15, "Good", 0.1, "Excellent"),  # 150 ms WS, 100 ms API
            (0.15, "Good", 0.4, "Fair"),  # 150 ms WS, 400 ms API
            (0.15, "Good", 0.7, "Poor"),  # 150 ms WS, 700 ms API
            (0.3, "Fair", 0.1, "Excellent"),  # 300 ms WS, 100 ms API
            (0.3, "Fair", 0.4, "Fair"),  # 300 ms WS, 400 ms API
            (0.3, "Fair", 0.7, "Poor"),  # 300 ms WS, 700 ms API
            (0.6, "Poor", 0.1, "Excellent"),  # 600 ms WS, 100 ms API
            (0.6, "Poor", 0.4, "Fair"),  # 600 ms WS, 400 ms API
            (0.6, "Poor", 0.7, "Poor"),  # 600 ms WS, 700 ms API
        ],
    )
    @async_test
    async def test_slash_ping_command(
        self,
        caplog: pytest.LogCaptureFixture,
        basic_commands_cog: BasicCommands,
        mock_interaction: MagicMock,
        ws_latency_seconds: float,
        expected_ws_status: str,
        api_latency_seconds: float,
        expected_api_status: str,
    ) -> None:
        """Test the slash ping command with various latency combinations"""
        # Mock bot startup time for uptime calculation
        current_time = time.time()
        basic_commands_cog.bot.startup_time = (
            current_time - 3661
        )  # 1 hour, 1 minute, 1 second ago

        # Calculate API latency timing for perf_counter mock
        api_start_time = 1.0
        api_end_time = api_start_time + api_latency_seconds

        # Mock bot latency and time.perf_counter
        with (
            patch(
                "discord.Client.latency",
                new_callable=PropertyMock,
                return_value=ws_latency_seconds,
            ),
            patch("time.perf_counter", side_effect=[api_start_time, api_end_time]),
            caplog.at_level(logging.INFO),
        ):
            await basic_commands_cog.slash_ping.callback(
                basic_commands_cog,  # pyrefly: ignore[bad-argument-type]
                mock_interaction,  # pyrefly: ignore[bad-argument-count]
            )

        # Verify an initial response was sent with an embed
        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert call_args is not None
        assert "embed" in call_args.kwargs
        embed_arg = call_args.kwargs["embed"]
        assert isinstance(embed_arg, discord.Embed)
        assert embed_arg.title == "🏓 Pong!"
        assert embed_arg.description is not None
        assert "Bot latency and response time information" in embed_arg.description

        # Verify edit_original_response was called
        mock_interaction.edit_original_response.assert_called_once()

        # Verify the embed contains expected status information
        edit_call_args = mock_interaction.edit_original_response.call_args
        assert edit_call_args is not None
        assert "embed" in edit_call_args.kwargs
        updated_embed = edit_call_args.kwargs["embed"]

        # Check that the embed fields contain expected status values
        embed_dict = updated_embed.to_dict()
        field_values = [field["value"] for field in embed_dict.get("fields", [])]

        # Verify WebSocket status is in one of the field values
        ws_found = any(expected_ws_status in value for value in field_values)
        assert ws_found, (
            f"Expected WebSocket status '{expected_ws_status}' "
            f"not found in embed fields"
        )

        # Verify API status is in one of the field values
        api_found = any(expected_api_status in value for value in field_values)
        assert api_found, (
            f"Expected API status '{expected_api_status}' not found in embed fields"
        )

        # Verify logging
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"
        assert (
            record.message == f"Received slash 'ping' from TestUser in channel "
            f"{mock_interaction.channel}"
        )
        assert record.name == "lib.cogs.basic_commands"

    @async_test
    async def test_slash_ping_command_without_startup_time(
        self,
        caplog: pytest.LogCaptureFixture,
        basic_commands_cog: BasicCommands,
        mock_interaction: MagicMock,
    ) -> None:
        """
        Test the slash ping command when the bot doesn't have a startup_time attribute
        """
        # Ensure bot doesn't have a startup_time attribute
        if hasattr(basic_commands_cog.bot, "startup_time"):
            delattr(basic_commands_cog.bot, "startup_time")

        # Mock bot latency and time.perf_counter for API response time measurement
        with (
            patch(
                "discord.Client.latency", new_callable=PropertyMock, return_value=0.1
            ),
            patch("time.perf_counter", side_effect=[1.0, 1.1]),
            caplog.at_level(logging.INFO),
        ):
            await basic_commands_cog.slash_ping.callback(
                basic_commands_cog,  # pyrefly: ignore[bad-argument-type]
                mock_interaction,  # pyrefly: ignore[bad-argument-count]
            )

        # Verify responses were called
        mock_interaction.response.send_message.assert_called_once()
        mock_interaction.edit_original_response.assert_called_once()

        # Verify logging
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"
        assert (
            record.message == f"Received slash 'ping' from TestUser in channel "
            f"{mock_interaction.channel}"
        )

    @async_test
    async def test_slash_ping_command_edit_failure(
        self,
        caplog: pytest.LogCaptureFixture,
        basic_commands_cog: BasicCommands,
        mock_interaction: MagicMock,
    ) -> None:
        """Test the slash ping command when edit_original_response fails"""
        # Mock edit_original_response to raise discord.NotFound
        mock_interaction.edit_original_response.side_effect = discord.NotFound(
            MagicMock(), "Not found"
        )

        # Mock bot latency and time.perf_counter for API response time measurement
        with (
            patch(
                "discord.Client.latency", new_callable=PropertyMock, return_value=0.2
            ),
            patch("time.perf_counter", side_effect=[1.0, 1.2]),
            caplog.at_level(logging.WARNING),
        ):
            await basic_commands_cog.slash_ping.callback(
                basic_commands_cog,  # pyrefly: ignore[bad-argument-type]
                mock_interaction,  # pyrefly: ignore[bad-argument-count]
            )

        # Verify an initial response was sent
        mock_interaction.response.send_message.assert_called_once()

        # Verify edit was attempted
        mock_interaction.edit_original_response.assert_called_once()

        # Verify warning was logged
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        assert warning_records[0].message == "Could not edit original ping response"

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
            import lib.cogs.basic_commands as basic_commands_module  # noqa: PLC0415

            importlib.reload(basic_commands_module)

            # Verify the module is properly loaded
            assert hasattr(basic_commands_module, "BasicCommands")
