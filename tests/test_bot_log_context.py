"""Unit tests for bot_log_context.py"""

from unittest.mock import MagicMock

import discord
import pytest
from pytest_mock import MockerFixture

from lib.bot_log_context import LogContext


@pytest.fixture(autouse=True)
def mock_config(mocker: MockerFixture) -> MagicMock:
    """Mock the config object"""
    mock_config = mocker.patch("lib.bot_log_context.config")
    mock_config.LOG_CHANNEL = mocker.MagicMock(spec=discord.TextChannel)
    return mock_config


class TestLogContext:
    """Unit tests for the LogContext dataclass."""

    def test_defaults(self, mock_config: MagicMock) -> None:
        """Test that LogContext initializes with default values."""
        log_context = LogContext(log_message="Test log")

        assert log_context.log_message == "Test log"
        assert log_context.log_channel == mock_config.LOG_CHANNEL
        assert log_context.level == "INFO"
        assert log_context.action is None
        assert log_context.user is None
        assert log_context.channel is None
        assert log_context.embed is False
        assert log_context.color == discord.Color.blue()  # Default for level "INFO"

    def test_defaults_with_log_channel(self) -> None:
        """Test that LogContext initializes with a custom log channel."""
        mock_channel = MagicMock(spec=discord.TextChannel)
        log_context = LogContext(log_message="Test log", log_channel=mock_channel)

        assert log_context.log_channel == mock_channel

    def test_missing_log_channel_config(
        self,
        mock_config: MagicMock,
    ) -> None:
        """
        Test that an exception is raised if log_channel is missing
        and config.LOG_CHANNEL is None
        """
        mock_config.LOG_CHANNEL = None

        with pytest.raises(AttributeError, match="Logging channel not found"):
            LogContext(log_message="Test log")

    @pytest.mark.parametrize(
        ("level", "expected_color"),
        [
            ("CRITICAL", discord.Color.dark_red()),
            ("ERROR", discord.Color.red()),
            ("WARNING", discord.Color.orange()),
            ("INFO", discord.Color.blue()),
            ("DEBUG", discord.Color.light_grey()),
            ("INVALID", discord.Color.default()),  # Fallback to default
        ],
    )
    def test_level_color(
        self,
        level: str,
        expected_color: discord.Color,
    ) -> None:
        """Test that the correct color is assigned based on the log level."""
        log_context = LogContext(log_message="Test log", level=level)
        assert log_context.color == expected_color

    def test_color_override(self) -> None:
        """Test that the color can be overridden."""
        log_context = LogContext(log_message="Test log", color=discord.Color.green())
        assert log_context.color == discord.Color.green()

    # TODO @Cyberops7: use mock_channel fixture
    def test_user_and_channel_fields(self) -> None:
        """Test that LogContext can set user and channel fields."""
        mock_user = MagicMock(spec=discord.Member)
        mock_user.mention = "@TestUser"
        mock_user.id = 67890

        mock_channel = MagicMock(spec=discord.TextChannel)
        mock_channel.mention = "#general"
        mock_channel.id = 12345

        log_context = LogContext(
            log_message="Test log",
            user=mock_user,
            channel=mock_channel,
        )

        assert log_context.user == mock_user
        assert log_context.channel == mock_channel
        assert log_context.user is not None, "User should not be None"
        assert log_context.user.mention == "@TestUser"
        assert log_context.channel is not None, "Channel should not be None"
        assert log_context.channel.mention == "#general"

    def test_embed_flag(self) -> None:
        """Test the embed flag behavior in LogContext."""
        log_context = LogContext(log_message="Test log", embed=True)
        assert log_context.embed is True

    def test_action_field(self) -> None:
        """Test the action field is correctly initialized."""
        log_context = LogContext(log_message="Test log", action="Custom Action")
        assert log_context.action == "Custom Action"
