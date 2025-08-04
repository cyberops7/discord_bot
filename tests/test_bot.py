"""Unit tests for bot.py"""

import datetime
import logging
from collections.abc import Iterator
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from discord import Intents
from pytest_mock import MockerFixture

from lib.bot import DiscordBot, LogContext
from lib.config import config
from lib.utils import async_test


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
    bot = DiscordBot(intents=intents)

    with patch.object(type(bot), "user", mock_bot_user):
        yield bot


@pytest.fixture
def mock_config(mocker: MockerFixture) -> MagicMock:
    """Mock the config object"""
    mock_config = mocker.patch("lib.bot.config")
    mock_config.CHANNELS.BOT_LOGS = 101
    mock_config.CHANNELS.BOT_PLAYGROUND = 123
    mock_config.CHANNELS.MOUSETRAP = 456
    mock_config.ROLES.ADMIN = 11111
    mock_config.ROLES.JIMS_GARAGE = 22222
    mock_config.ROLES.MOD = 33333
    mock_config.TIMEZONE = datetime.UTC
    return mock_config


@pytest.fixture
def mock_channel(channel_id: int = 999) -> MagicMock:
    """Mock discord.abc.Messageable fixture"""
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = channel_id  # Default to None; set it as needed in tests
    channel.mention = f"<#{channel_id}>"
    channel.name = "test-channel"
    channel.send = AsyncMock()
    return channel


@pytest.fixture(autouse=True)
def mock_default_log_channel(
    mocker: MockerFixture, mock_channel: MagicMock, mock_config: MagicMock
) -> MagicMock:
    """Mock the DiscordBot.default_log_channel class variable in bot.py"""
    default_channel = mock_channel(
        channel_id=mock_config.CHANNELS.BOT_LOGS
    )  # Use BOT_LOGS channel ID
    default_channel.send = AsyncMock()

    mocker.patch("lib.bot.DiscordBot.default_log_channel", default_channel)

    return default_channel


@pytest.fixture
def mock_message(mock_user: MagicMock, mock_channel: MagicMock) -> MagicMock:
    """Mock discord.Message fixture"""
    message = MagicMock(spec=discord.Message)
    message.author = mock_user
    message.channel = mock_channel
    message.content = "test message"
    return message


class TestLogContext:
    """Unit tests for the LogContext dataclass."""

    @pytest.mark.usefixtures("mock_config")
    def test_defaults(self, mock_default_log_channel: MagicMock) -> None:
        """Test that LogContext initializes with default values."""
        log_context = LogContext(log_message="Test log")

        assert log_context.log_message == "Test log"
        assert log_context.log_channel == mock_default_log_channel
        assert log_context.level == "INFO"
        assert log_context.action is None
        assert log_context.user is None
        assert log_context.channel is None
        assert log_context.embed is False
        assert log_context.color == discord.Color.blue()  # Default for level "INFO"

    def test_missing_log_channel(
        self,
        mock_config: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        """
        Test that an exception is raised if log_channel is missing
        and DiscordBot.default_log_channel is None
        """
        # Temporarily patch DiscordBot.default_log_channel to None for this test
        mocker.patch("lib.bot.DiscordBot.default_log_channel", None)
        del mock_config.CHANNELS.BOT_LOGS

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


class TestDiscordBot:
    """Test cases for DiscordBot class"""

    def test_inheritance(self, discord_bot: DiscordBot) -> None:
        """Test that DiscordBot inherits from discord.Client"""
        assert isinstance(discord_bot, discord.Client)

    @async_test
    async def test_close_success(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
    ) -> None:
        """Test that the close method successfully logs the shutdown event
        and calls super().close().
        """
        mock_log_bot_event = mocker.patch.object(
            discord_bot, "log_bot_event", AsyncMock()
        )
        mock_super_close = mocker.patch("discord.Client.close", AsyncMock())

        with caplog.at_level(logging.WARNING):
            await discord_bot.close()

        mock_log_bot_event.assert_called_once_with(
            event="Bot Shutdown",
            details=mocker.ANY,  # Version will vary based on the mocked config
            level="WARNING",
        )
        mock_super_close.assert_called_once()
        assert len(caplog.records) == 0  # make sure no WARNINGS were logged

    @async_test
    @pytest.mark.parametrize(
        ("exception", "exception_message"),
        [
            (
                RuntimeError("Test runtime error"),
                "Error during close: Test runtime error",
            ),
            (OSError("Test OS error"), "Error during close: Test OS error"),
            (
                discord.ConnectionClosed(
                    socket=MagicMock(),
                    shard_id=0,
                    code=4004,
                ),
                "Error during close:",
            ),
        ],
    )
    async def test_close_exceptions(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        exception: Exception,
        exception_message: str,
    ) -> None:
        """Test that exceptions during super().close() are properly logged."""
        mocker.patch.object(discord_bot, "log_bot_event", AsyncMock())
        mock_super_close = mocker.patch(
            "discord.Client.close", AsyncMock(side_effect=exception)
        )

        with caplog.at_level(logging.WARNING):
            await discord_bot.close()

        # Ensure the exception is logged
        assert len(caplog.records) == 1
        assert exception_message in caplog.records[0].message

        mock_super_close.assert_called_once()

    @async_test
    async def test_get_log_channel_valid_channel(
        self, mocker: MockerFixture, discord_bot: DiscordBot, mock_config: MagicMock
    ) -> None:
        """Test _get_log_channel when a valid TextChannel is returned."""
        mock_text_channel = MagicMock(spec=discord.TextChannel)
        mocked_get_channel = mocker.patch.object(
            discord_bot, "get_channel", return_value=mock_text_channel
        )

        result = await discord_bot._get_log_channel()

        mocked_get_channel.assert_called_once_with(mock_config.CHANNELS.BOT_LOGS)
        assert result == mock_text_channel

    @async_test
    async def test_get_log_channel_non_text_channel(
        self,
        mocker: MockerFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test _get_log_channel when a non-TextChannel is returned."""
        mock_voice_channel = MagicMock(spec=discord.VoiceChannel)
        mocked_get_channel = mocker.patch.object(
            discord_bot, "get_channel", return_value=mock_voice_channel
        )

        with caplog.at_level(logging.WARNING):
            result = await discord_bot._get_log_channel()

        mocked_get_channel.assert_called_once_with(mock_config.CHANNELS.BOT_LOGS)
        assert result is None
        assert len(caplog.records) == 1
        assert "BOT_LOGS channel ID" in caplog.records[0].message
        assert "is not a TextChannel" in caplog.records[0].message

    @async_test
    async def test_get_log_channel_none(
        self, mocker: MockerFixture, discord_bot: DiscordBot, mock_config: MagicMock
    ) -> None:
        """Test _get_log_channel when get_channel returns None."""
        # Arrange
        mocker.patch.object(discord_bot, "get_channel", return_value=None)

        # Act
        result = await discord_bot._get_log_channel()

        # Assert
        discord_bot.get_channel.assert_called_once_with(mock_config.CHANNELS.BOT_LOGS)
        assert result is None

    @async_test
    @pytest.mark.usefixtures("mock_config")
    async def test_send_log_embed_basic(
        self,
        caplog: pytest.LogCaptureFixture,
        mock_default_log_channel: MagicMock,
    ) -> None:
        """Test sending a basic log embed without user or channel details."""
        context = LogContext(
            log_message="Test log message",
            log_channel=mock_default_log_channel,
            level="INFO",
            action="Test Action",
            embed=True,
        )

        with caplog.at_level(logging.INFO):
            result = await DiscordBot._send_log_embed(context)

        mock_default_log_channel.send.assert_called_once()
        embed = mock_default_log_channel.send.call_args[1]["embed"]
        assert embed.title == "Test Action"
        assert embed.description == "Test log message"
        assert embed.color == discord.Color.blue()
        assert result == mock_default_log_channel.send.return_value

        assert len(caplog.records) == 1
        assert (
            f"Sending embed log message: {embed.to_dict()}" in caplog.records[0].message
        )

    @async_test
    async def test_send_log_embed_none_log_channel(self, mocker: MockerFixture) -> None:
        """Test that _send_log_embed raises ValueError when log_channel is None."""
        mocker.patch("lib.bot.DiscordBot.default_log_channel", None)

        # Create a context with a direct None log_channel
        # that will bypass the __post_init__ check
        context = MagicMock(spec=LogContext)
        context.log_message = "Test log message"
        context.log_channel = None
        context.level = "INFO"
        context.embed = True
        context.user = None
        context.channel = None
        context.color = discord.Color.blue()

        with pytest.raises(
            ValueError, match="Cannot send log message: log_channel is None"
        ):
            await DiscordBot._send_log_embed(context)

    @async_test
    async def test_send_log_embed_with_user_and_channel(
        self, mocker: MockerFixture, mock_channel: MagicMock, mock_user: MagicMock
    ) -> None:
        """Test sending a log embed with user and channel details."""
        mock_send = mocker.patch.object(mock_channel, "send", AsyncMock())
        mock_channel.mention = "#test-channel"

        context = LogContext(
            log_message="User action log",
            log_channel=mock_channel,
            level="WARNING",
            action="User Action",
            embed=True,
            user=mock_user,
            channel=mock_channel,
            color=discord.Color.orange(),
        )

        result = await DiscordBot._send_log_embed(context)

        mock_send.assert_called_once()
        embed = mock_send.call_args[1]["embed"]
        assert embed.title == "User Action"
        assert embed.description == "User action log"
        assert embed.color == discord.Color.orange()

        user_field = embed.fields[0]
        assert user_field.name == "User"
        assert user_field.value == f"{mock_user.mention}\n`{mock_user.id}`"

        channel_field = embed.fields[1]
        assert channel_field.name == "Channel"
        assert channel_field.value == f"#test-channel\n`{mock_channel.id}`"

        assert result == mock_send.return_value

    @async_test
    async def test_send_log_text_basic(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        mock_channel: MagicMock,
    ) -> None:
        """Test sending a basic log text without user or channel details."""
        # Arrange
        mock_send = mocker.patch.object(mock_channel, "send", AsyncMock())
        timestamp = datetime.datetime.now(
            cast("datetime.tzinfo", config.TIMEZONE)
        ).strftime("%Y-%m-%d %H:%M:%S")
        context = LogContext(
            log_message="Test log message",
            log_channel=mock_channel,
            level="INFO",
            action=None,
            embed=False,
        )

        with caplog.at_level(logging.INFO):
            result = await DiscordBot._send_log_text(context)

        mock_send.assert_called_once()
        log_message = mock_send.call_args[0][0]
        assert f"[{timestamp}] [INFO]" in log_message
        assert "Test log message" in log_message
        assert result == mock_send.return_value

        assert len(caplog.records) == 1
        assert f"Sending text log message: {log_message}" in caplog.records[0].message

    @async_test
    async def test_send_log_text_none_log_channel(self, mocker: MockerFixture) -> None:
        """Test that _send_log_text raises ValueError when log_channel is None."""
        # Temporarily patch default_log_channel to None
        mocker.patch("lib.bot.DiscordBot.default_log_channel", None)

        # Create a context with a direct None log_channel
        # that will bypass the __post_init__ check
        context = MagicMock(spec=LogContext)
        context.log_message = "Test log message"
        context.log_channel = None
        context.level = "INFO"
        context.embed = False
        context.user = None
        context.channel = None

        with pytest.raises(
            ValueError, match="Cannot send log message: log_channel is None"
        ):
            await DiscordBot._send_log_text(context)

    @async_test
    async def test_send_log_text_with_user_and_channel(
        self, mocker: MockerFixture, mock_channel: MagicMock, mock_user: MagicMock
    ) -> None:
        """Test sending a log text with user and channel details."""
        # Arrange
        mock_send = mocker.patch.object(mock_channel, "send", AsyncMock())
        timestamp = datetime.datetime.now(
            cast("datetime.tzinfo", config.TIMEZONE)
        ).strftime("%Y-%m-%d %H:%M:%S")
        mock_channel.mention = "#test-channel"

        context = LogContext(
            log_message="User action log",
            log_channel=mock_channel,
            level="WARNING",
            action="User Action",
            embed=False,
            user=mock_user,
            channel=mock_channel,
        )

        # Act
        result = await DiscordBot._send_log_text(context)

        # Assert
        mock_send.assert_called_once()
        log_message = mock_send.call_args[0][0]
        assert f"[{timestamp}] [WARNING]" in log_message
        assert "**User Action**" in log_message
        assert "User action log" in log_message
        assert f"| User: {mock_user.mention} ({mock_user.id})" in log_message
        assert f"| Channel: {mock_channel.mention} ({mock_channel.id})" in log_message
        assert result == mock_send.return_value

    @async_test
    async def test_log_to_channel_with_embed(
        self,
        discord_bot: DiscordBot,
        mock_channel: MagicMock,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test that log_to_channel sends an embed when context.embed is True."""
        mock_context = LogContext(
            log_message="Test embed log message",
            log_channel=mock_channel,
            embed=True,
        )
        mock_send_embed = mocker.patch.object(
            DiscordBot, "_send_log_embed", AsyncMock(return_value="embed_message")
        )

        with caplog.at_level(logging.ERROR):
            result = await discord_bot.log_to_channel(mock_context)

        mock_send_embed.assert_called_once_with(mock_context)
        assert result == "embed_message"
        assert len(caplog.records) == 0

    @async_test
    async def test_log_to_channel_without_embed(
        self,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_channel: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        """Test that log_to_channel sends a text log when context.embed is False."""
        mock_context = LogContext(
            log_message="Test text log message",
            log_channel=mock_channel,
            embed=False,
        )
        mock_send_text = mocker.patch.object(
            DiscordBot, "_send_log_text", AsyncMock(return_value="text_message")
        )

        with caplog.at_level(logging.ERROR):
            result = await discord_bot.log_to_channel(mock_context)

        mock_send_text.assert_called_once_with(mock_context)
        assert result == "text_message"
        assert len(caplog.records) == 0

    @async_test
    async def test_log_to_channel_http_exception(
        self,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_channel: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        """Test that log_to_channel handles discord.HTTPException gracefully."""
        mock_context = LogContext(
            log_message="Test log message",
            log_channel=mock_channel,
            embed=False,
        )
        mock_http_response = mocker.Mock()
        mock_send_text = mocker.patch.object(
            DiscordBot,
            "_send_log_text",
            AsyncMock(
                side_effect=discord.HTTPException(mock_http_response, "Test HTTP error")
            ),
        )

        result = await discord_bot.log_to_channel(mock_context)

        mock_send_text.assert_called_once_with(mock_context)
        assert result is None

        # Verify exception was logged
        assert len(caplog.records) == 1
        assert "Failed to send log message" in caplog.records[0].message
        assert caplog.records[0].levelname == "ERROR"

    @async_test
    @pytest.mark.parametrize(
        ("method_name", "expected_level"),
        [
            ("log_critical", "CRITICAL"),
            ("log_error", "ERROR"),
            ("log_warning", "WARNING"),
            ("log_info", "INFO"),
            ("log_debug", "DEBUG"),
        ],
    )
    async def test_log_level_methods(
        self,
        mocker: MockerFixture,
        discord_bot: DiscordBot,
        mock_channel: MagicMock,
        method_name: str,
        expected_level: str,
    ) -> None:
        """
        Test that the log_* methods set the correct level
        and delegate to log_to_channel.
        """
        # Arrange
        method = getattr(discord_bot, method_name)
        mock_context = LogContext(
            log_message="Test log message", log_channel=mock_channel
        )
        mock_log_to_channel = mocker.patch.object(
            discord_bot, "log_to_channel", AsyncMock(return_value="logged_message")
        )

        result = await method(mock_context)

        assert mock_context.level == expected_level
        mock_log_to_channel.assert_called_once_with(mock_context)
        assert result == "logged_message"

    @async_test
    async def test_log_bot_event_with_defaults(
        self,
        discord_bot: DiscordBot,
        mocker: MockerFixture,
    ) -> None:
        """Test log_bot_event with default parameters"""
        mock_log_to_channel = mocker.patch.object(
            discord_bot, "log_to_channel", AsyncMock(return_value="event_message")
        )

        result = await discord_bot.log_bot_event(event="Test Event")

        mock_log_to_channel.assert_called_once()
        context = mock_log_to_channel.call_args[0][0]
        assert context.log_message == "Bot event: Test Event"
        assert context.level == "INFO"
        assert context.action == "Bot Event"
        assert context.embed is True
        assert result == "event_message"

    @async_test
    async def test_log_bot_event_with_details(
        self,
        mocker: MockerFixture,
        discord_bot: DiscordBot,
    ) -> None:
        """Test log_bot_event with event details"""
        mock_log_to_channel = mocker.patch.object(
            discord_bot, "log_to_channel", AsyncMock(return_value="event_message")
        )

        result = await discord_bot.log_bot_event(
            event="Test Event", details="This is a test event with details"
        )

        mock_log_to_channel.assert_called_once()
        context = mock_log_to_channel.call_args[0][0]
        assert (
            context.log_message
            == "Bot event: Test Event\nDetails: This is a test event with details"
        )
        assert context.level == "INFO"
        assert context.action == "Bot Event"
        assert context.embed is True
        assert result == "event_message"

    @async_test
    async def test_log_bot_event_with_custom_level(
        self,
        discord_bot: DiscordBot,
        mocker: MockerFixture,
    ) -> None:
        """Test log_bot_event with a custom log level"""
        mock_log_to_channel = mocker.patch.object(
            discord_bot, "log_to_channel", AsyncMock(return_value="event_message")
        )

        result = await discord_bot.log_bot_event(event="Warning Event", level="WARNING")

        mock_log_to_channel.assert_called_once()
        context = mock_log_to_channel.call_args[0][0]
        assert context.log_message == "Bot event: Warning Event"
        assert context.level == "WARNING"
        assert context.action == "Bot Event"
        assert context.embed is True
        assert result == "event_message"

    @async_test
    async def test_log_bot_event_with_custom_channel(
        self,
        discord_bot: DiscordBot,
        mock_channel: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        """Test log_bot_event with a custom log channel"""
        mock_log_to_channel = mocker.patch.object(
            discord_bot, "log_to_channel", AsyncMock(return_value="event_message")
        )

        result = await discord_bot.log_bot_event(
            event="Channel Event", log_channel=mock_channel
        )

        mock_log_to_channel.assert_called_once()
        context = mock_log_to_channel.call_args[0][0]
        assert context.log_message == "Bot event: Channel Event"
        assert context.level == "INFO"
        assert context.action == "Bot Event"
        assert context.embed is True
        assert context.log_channel == mock_channel
        assert result == "event_message"

    @async_test
    async def test_log_bot_event_with_all_parameters(
        self,
        discord_bot: DiscordBot,
        mock_channel: MagicMock,
        mocker: MockerFixture,
    ) -> None:
        """Test log_bot_event with all parameters customized"""
        mock_log_to_channel = mocker.patch.object(
            discord_bot, "log_to_channel", AsyncMock(return_value="event_message")
        )

        result = await discord_bot.log_bot_event(
            event="Critical Event",
            level="CRITICAL",
            details="This is a critical event with all parameters",
            log_channel=mock_channel,
        )

        mock_log_to_channel.assert_called_once()
        context = mock_log_to_channel.call_args[0][0]
        assert context.log_message == (
            "Bot event: Critical Event\nDetails: "
            "This is a critical event with all parameters"
        )
        assert context.level == "CRITICAL"
        assert context.action == "Bot Event"
        assert context.embed is True
        assert context.log_channel == mock_channel
        assert result == "event_message"

    @async_test
    @pytest.mark.usefixtures("mock_channel", "mock_config")
    async def test_log_moderation_action_basic(
        self,
        mocker: MockerFixture,
        discord_bot: DiscordBot,
        mock_mod: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test basic moderation action logging with minimal parameters."""
        action = "Test Action"
        reason = "Test Reason"
        mock_log_to_channel = mocker.patch.object(
            discord_bot, "log_to_channel", AsyncMock(return_value="event_message")
        )

        result = await discord_bot.log_moderation_action(
            mock_mod, mock_user, action, reason
        )

        assert result == "event_message"
        mock_log_to_channel.assert_called_once()
        call_args = mock_log_to_channel.call_args_list[0][0][0]
        assert call_args.action == f"Moderation: {action}"
        assert call_args.level == "WARNING"
        assert call_args.user == mock_mod
        assert mock_user.mention in call_args.log_message
        assert reason in call_args.log_message
        assert call_args.embed

    @async_test
    async def test_log_moderation_action_with_channel(
        self,
        mocker: MockerFixture,
        discord_bot: DiscordBot,
        mock_channel: MagicMock,
        mock_config: MagicMock,
        mock_mod: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test moderation action logging with `log_channel` specified."""
        action = "Ban"
        reason = "Spam"
        mock_extra_channel = mock_channel(
            channel_id=mock_config.CHANNELS.BOT_PLAYGROUND
        )
        mock_log_channel = mock_channel(channel_id=mock_config.CHANNELS.BOT_LOGS)
        mock_log_to_channel = mocker.patch.object(
            discord_bot, "log_to_channel", AsyncMock(return_value="event_message")
        )

        result = await discord_bot.log_moderation_action(
            moderator=mock_mod,
            target=mock_user,
            action=action,
            reason=reason,
            extra_log_channel=mock_extra_channel,
        )

        assert result == "event_message"
        assert mock_log_to_channel.call_count == 2
        assert (
            mock_log_to_channel.call_args_list[0][0][0].log_channel
            == mock_extra_channel
        )
        call_args = mock_log_to_channel.call_args_list[1][0][0]
        assert call_args.action == f"Moderation: {action}"
        assert call_args.level == "WARNING"
        assert call_args.user == mock_mod
        assert call_args.log_channel == mock_log_channel
        assert mock_user.mention in call_args.log_message
        assert reason in call_args.log_message
        assert call_args.embed is True

    @async_test
    async def test_log_user_action_basic(
        self,
        mocker: MockerFixture,
        discord_bot: DiscordBot,
        mock_user: MagicMock,
    ) -> None:
        """Test basic user action logging with minimal parameters."""
        action = "Test Action"
        mock_log_to_channel = mocker.patch.object(
            discord_bot, "log_to_channel", AsyncMock(return_value="event_message")
        )

        result = await discord_bot.log_user_action(mock_user, action)

        assert result == "event_message"
        mock_log_to_channel.assert_called_once()
        call_args = mock_log_to_channel.call_args_list[0][0][0]
        assert call_args.action == f"User Action: {action}"
        assert call_args.level == "INFO"
        assert call_args.user == mock_user
        assert mock_user.mention in call_args.log_message
        assert call_args.embed

    @async_test
    async def test_log_user_action_details(
        self,
        mocker: MockerFixture,
        discord_bot: DiscordBot,
        mock_user: MagicMock,
    ) -> None:
        """Test detailed user action logging with details specified."""
        action = "Test Action"
        details = "Test Details"
        mock_log_to_channel = mocker.patch.object(
            discord_bot, "log_to_channel", AsyncMock(return_value="event_message")
        )

        result = await discord_bot.log_user_action(mock_user, action, details)

        assert result == "event_message"
        mock_log_to_channel.assert_called_once()
        call_args = mock_log_to_channel.call_args_list[0][0][0]
        assert call_args.action == f"User Action: {action}"
        assert call_args.level == "INFO"
        assert call_args.user == mock_user
        assert mock_user.mention in call_args.log_message
        assert details in call_args.log_message
        assert call_args.embed

    def test_has_privileged_role(
        self,
        discord_bot: DiscordBot,
        caplog: pytest.LogCaptureFixture,
        mock_config: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test the user privileged role check"""
        test_cases = [
            (mock_config.ROLES.ADMIN, True),
            (mock_config.ROLES.JIMS_GARAGE, True),
            (mock_config.ROLES.MOD, True),
            (56789, False),  # Example of a non-privileged role
        ]
        mock_user = mock_user()

        for role_id, expected_result in test_cases:
            caplog.clear()
            mock_user.roles = [
                MagicMock(id=12345),
                MagicMock(id=role_id),
            ]
            with caplog.at_level(logging.DEBUG):
                result = discord_bot._has_privileged_role(mock_user)

            assert result == expected_result
            assert len(caplog.records) == 2

    @async_test
    async def test_ban_spammer_not_member_instance(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_message: MagicMock,
    ) -> None:
        """Test that a non-member instance is not banned"""
        mock_message.author = mocker.MagicMock(spec=discord.User)
        with caplog.at_level(logging.INFO):
            await discord_bot.ban_spammer(mock_message)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "WARNING"
        assert caplog.records[0].message == (
            "Message author is not a Member object, skipping `ban_spammer`."
        )

    @async_test
    async def test_ban_spammer_not_text_channel(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_message: MagicMock,
    ) -> None:
        """Test that a non-member instance is not banned"""
        mock_message.channel = mocker.MagicMock(spec=discord.DMChannel)
        with caplog.at_level(logging.INFO):
            await discord_bot.ban_spammer(mock_message)

        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "WARNING"
        assert caplog.records[0].message == (
            "Message channel is not a TextChannel, skipping `ban_spammer`"
        )

    @async_test
    async def test_ban_spammer_privileged_role(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
        mock_message: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test that a privileged role is not banned"""
        mock_mod_role = MagicMock(spec=discord.Role)
        mock_mod_role.id = mock_config.ROLES.MOD
        mock_mod_role.name = "Moderator"
        mock_user.roles = [mock_mod_role]
        mock_message.author = mock_user

        mocked_log_to_channel = mocker.patch("lib.bot.DiscordBot.log_to_channel")
        mocked_has_privileged_role = mocker.patch(
            "lib.bot.DiscordBot._has_privileged_role", return_value=True
        )

        with caplog.at_level(logging.INFO):
            await discord_bot.ban_spammer(mock_message)

        mocked_has_privileged_role.assert_called_once()
        mocked_log_to_channel.assert_called_once()
        assert len(caplog.records) == 2
        assert caplog.records[0].levelname == "INFO"
        assert (
            caplog.records[0].message
            == f"Processing potential spam from user {mock_user.display_name} "
            f"({mock_user.id}) in channel #{mock_message.channel.name}"
        )
        assert caplog.records[1].levelname == "INFO"
        assert (
            caplog.records[1].message
            == f"User {mock_user.display_name} ({mock_user.id}) has privileged role, "
            f"not banning"
        )

    @async_test
    @pytest.mark.usefixtures("mock_config")
    async def test_ban_spammer_success(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_message: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test that a regular user gets banned"""
        mocked_has_privileged_role = mocker.patch(
            "lib.bot.DiscordBot._has_privileged_role", return_value=False
        )
        mocked_ban = mocker.patch.object(mock_user, "ban", new_callable=AsyncMock)
        mocked_log_moderation_action = mocker.patch(
            "lib.bot.DiscordBot.log_moderation_action"
        )

        with caplog.at_level(logging.INFO):
            await discord_bot.ban_spammer(mock_message)

        mocked_has_privileged_role.assert_called_once()
        mocked_ban.assert_called_once()
        mocked_log_moderation_action.assert_called_once()
        assert len(caplog.records) == 3
        assert caplog.records[0].levelname == "INFO"
        assert (
            caplog.records[0].message
            == f"Processing potential spam from user {mock_user.display_name} "
            f"({mock_user.id}) in channel #{mock_message.channel.name}"
        )
        assert caplog.records[1].levelname == "WARNING"
        assert (
            caplog.records[1].message
            == f"Banning user {mock_user.display_name} ({mock_user.id}) for spam in "
            f"channel #{mock_message.channel.name}"
        )
        assert caplog.records[2].levelname == "WARNING"
        assert (
            caplog.records[2].message
            == f"Successfully banned user {mock_user.display_name} ({mock_user.id}) "
            f"for spam"
        )

    @async_test
    @pytest.mark.usefixtures("mock_config")
    async def test_ban_spammer_forbidden(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_message: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test that Forbidden exception is handled when banning a user"""
        mocked_has_privileged_role = mocker.patch(
            "lib.bot.DiscordBot._has_privileged_role", return_value=False
        )
        mocked_ban = mocker.patch.object(
            mock_user,
            "ban",
            new_callable=AsyncMock,
            side_effect=discord.Forbidden(MagicMock(), "Missing Permissions"),
        )
        mocked_log_error = mocker.patch("lib.bot.DiscordBot.log_error")

        with caplog.at_level(logging.INFO):
            await discord_bot.ban_spammer(mock_message)

        mocked_has_privileged_role.assert_called_once()
        mocked_ban.assert_called_once()
        mocked_log_error.assert_called_once()

        # Check log messages
        assert len(caplog.records) == 3
        assert caplog.records[0].levelname == "INFO"
        assert (
            caplog.records[0].message
            == f"Processing potential spam from user {mock_user.display_name} "
            f"({mock_user.id}) in channel #{mock_message.channel.name}"
        )
        assert caplog.records[1].levelname == "WARNING"
        assert (
            caplog.records[1].message
            == f"Banning user {mock_user.display_name} ({mock_user.id}) for spam in "
            f"channel #{mock_message.channel.name}"
        )
        assert caplog.records[2].levelname == "ERROR"
        assert "Bot lacks permission to ban user" in caplog.records[2].message

    @async_test
    @pytest.mark.usefixtures("mock_config")
    async def test_ban_spammer_http_exception(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_message: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test that HTTPException is handled when banning a user"""
        mocked_has_privileged_role = mocker.patch(
            "lib.bot.DiscordBot._has_privileged_role", return_value=False
        )
        # Mock the ban method to raise discord.HTTPException
        http_error = discord.HTTPException(MagicMock(), "HTTP Error")
        mocked_ban = mocker.patch.object(
            mock_user, "ban", new_callable=AsyncMock, side_effect=http_error
        )
        mocked_log_error = mocker.patch("lib.bot.DiscordBot.log_error")

        with caplog.at_level(logging.INFO):
            await discord_bot.ban_spammer(mock_message)

        mocked_has_privileged_role.assert_called_once()
        mocked_ban.assert_called_once()
        mocked_log_error.assert_called_once()

        # Check log messages
        assert len(caplog.records) == 3
        assert caplog.records[0].levelname == "INFO"
        assert (
            caplog.records[0].message
            == f"Processing potential spam from user {mock_user.display_name} "
            f"({mock_user.id}) in channel #{mock_message.channel.name}"
        )
        assert caplog.records[1].levelname == "WARNING"
        assert (
            caplog.records[1].message
            == f"Banning user {mock_user.display_name} ({mock_user.id}) for spam in "
            f"channel #{mock_message.channel.name}"
        )
        assert caplog.records[2].levelname == "ERROR"
        assert "HTTP error while banning user" in caplog.records[2].message

    @async_test
    @pytest.mark.usefixtures("mock_config")
    async def test_on_ready(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_default_log_channel: MagicMock,
    ) -> None:
        """Test the on_ready method"""
        mocker.patch.object(
            discord_bot, "_get_log_channel", return_value=mock_default_log_channel
        )
        mock_log_bot_event = mocker.patch("lib.bot.DiscordBot.log_bot_event")

        with caplog.at_level(logging.INFO):
            await discord_bot.on_ready()

        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "INFO"
        assert "We have logged in as TestBot" in caplog.records[0].message
        mock_log_bot_event.assert_called_once()

    @async_test
    async def test_on_ready_no_default_channel(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
    ) -> None:
        """Test the on_ready method logs correctly"""
        # Mock get_channel to return None to simulate when the channel is not found
        mocker.patch.object(discord_bot, "_get_log_channel", return_value=None)
        mock_log_bot_event = mocker.patch("lib.bot.DiscordBot.log_bot_event")

        with caplog.at_level(logging.INFO):
            await discord_bot.on_ready()

        assert len(caplog.records) == 2
        assert caplog.records[0].levelname == "INFO"
        assert "We have logged in as TestBot" in caplog.records[0].message
        assert caplog.records[1].levelname == "WARNING"
        assert (
            f"Could not find log channel with ID {mock_config.CHANNELS.BOT_LOGS}"
            in caplog.records[1].message
        )
        mock_log_bot_event.assert_called_once()

    @async_test
    async def test_on_message_self_message_ignored(
        self,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_message: MagicMock,
    ) -> None:
        """Test that messages from the bot itself are ignored"""
        mock_message.author = discord_bot.user

        await discord_bot.on_message(mock_message)

        assert len(caplog.records) == 0
        mock_message.channel.send.assert_not_called()

    @async_test
    async def test_on_message_self_message_no_logging(
        self,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_message: MagicMock,
    ) -> None:
        """Test that self messages don't generate logs"""
        mock_message.author = discord_bot.user
        mock_message.content = "hello"

        with caplog.at_level(logging.INFO):
            await discord_bot.on_message(mock_message)

        assert len(caplog.records) == 0

    @async_test
    @pytest.mark.usefixtures("mock_channel")
    async def test_on_message_mousetrap(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_message: MagicMock,
        mock_config: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test that mousetrap detection works"""
        mock_message.channel.id = mock_config.CHANNELS.MOUSETRAP
        mocked_ban_spammer = mocker.patch(
            "lib.bot.DiscordBot.ban_spammer", AsyncMock(return_value=None)
        )

        with caplog.at_level(logging.INFO):
            await discord_bot.on_message(mock_message)

        mocked_ban_spammer.assert_called_once()
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "WARNING"
        assert record.message == f"Received message from {mock_user} in #mousetrap"

    @async_test
    async def test_on_message_hello_response(
        self,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
        mock_message: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test that messages starting with 'hello' get a response"""
        mock_message.author = mock_user
        mock_message.channel.id = mock_config.CHANNELS.BOT_PLAYGROUND
        mock_message.content = "hello world"

        with caplog.at_level(logging.INFO):
            await discord_bot.on_message(mock_message)

        mock_message.channel.send.assert_called_once_with("Hello")
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"
        assert record.message == "Received 'hello' from TestUser"
        assert record.name == "lib.bot"

    @async_test
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
        mock_config: MagicMock,
        mock_message: MagicMock,
        mock_user: MagicMock,
        message_content: str,
    ) -> None:
        """Test that 'hello' detection is case-insensitive"""
        mock_message.author = mock_user
        mock_message.channel.id = mock_config.CHANNELS.BOT_PLAYGROUND
        mock_message.content = message_content

        await discord_bot.on_message(mock_message)

        mock_message.channel.send.assert_called_once_with("Hello")

    @async_test
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
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
        mock_message: MagicMock,
        mock_user: MagicMock,
        message_content: str,
    ) -> None:
        """Test that messages not starting with 'hello' don't get a response"""
        mock_message.author = mock_user
        mock_message.channel.id = mock_config.CHANNELS.BOT_PLAYGROUND
        mock_message.content = message_content

        await discord_bot.on_message(mock_message)

        assert len(caplog.records) == 0
        mock_message.channel.send.assert_not_called()

    @async_test
    async def test_on_message_ping_response(
        self,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
        mock_message: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test that messages starting with 'ping' get a response"""
        mock_message.author = mock_user
        mock_message.channel.id = mock_config.CHANNELS.BOT_PLAYGROUND
        mock_message.content = "ping"

        with caplog.at_level(logging.INFO):
            await discord_bot.on_message(mock_message)

        mock_message.channel.send.assert_called_once_with("Pong")
        assert len(caplog.records) == 1
        record = caplog.records[0]
        assert record.levelname == "INFO"
        assert record.message == "Received 'ping' from TestUser"
        assert record.name == "lib.bot"

    @async_test
    @pytest.mark.parametrize(
        "message_content",
        [
            "ping",
            "Ping",
            "PING",
            "ping pong",
            "ping ping ping",
        ],
    )
    async def test_on_message_ping_case_insensitive(
        self,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
        mock_message: MagicMock,
        mock_user: MagicMock,
        message_content: str,
    ) -> None:
        """Test that 'ping' detection is case-insensitive"""
        mock_message.author = mock_user
        mock_message.channel.id = mock_config.CHANNELS.BOT_PLAYGROUND
        mock_message.content = message_content

        await discord_bot.on_message(mock_message)

        mock_message.channel.send.assert_called_once_with("Pong")
