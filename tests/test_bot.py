"""Unit tests for bot.py"""

import datetime
import importlib
import logging
from types import ModuleType
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, MagicMock

if TYPE_CHECKING:
    from collections.abc import Callable

import discord
import pytest
from discord.ext import commands
from pytest_mock import MockerFixture

from lib.bot import DiscordBot
from lib.bot_log_context import LogContext
from lib.config import config
from tests.utils import async_test


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
        assert len(caplog.records) == 1  # make sure no WARNINGS were logged

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
        mocked_get_channel = mocker.patch.object(
            discord_bot, "get_channel", return_value=None
        )

        result = await discord_bot._get_log_channel()

        mocked_get_channel.assert_called_once_with(mock_config.CHANNELS.BOT_LOGS)
        assert result is None

    @async_test
    async def test_send_log_embed_basic(
        self,
        caplog: pytest.LogCaptureFixture,
        mock_config: MagicMock,
    ) -> None:
        """Test sending a basic log embed without user or channel details."""
        context = LogContext(
            log_message="Test log message",
            level="INFO",
            action="Test Action",
            embed=True,
        )

        with caplog.at_level(logging.INFO):
            result = await DiscordBot._send_log_embed(context)

        mock_config.LOG_CHANNEL.send.assert_called_once()
        embed = mock_config.LOG_CHANNEL.send.call_args[1]["embed"]
        assert embed.title == "Test Action"
        assert embed.description == "Test log message"
        assert embed.color == discord.Color.blue()
        assert result == mock_config.LOG_CHANNEL.send.return_value

        assert len(caplog.records) == 1
        assert (
            f"Sending embed log message: {embed.to_dict()}" in caplog.records[0].message
        )

    @async_test
    async def test_send_log_embed_none_log_channel(self) -> None:
        """Test that _send_log_embed raises ValueError when log_channel is None."""
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
        context.extra_embed_fields = []  # Add this line to fix the test

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
    async def test_send_log_embed_with_extra_fields(
        self,
        mocker: MockerFixture,
        mock_channel: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Test sending a log embed with extra_embed_fields."""
        mock_send = mocker.patch.object(mock_channel, "send", AsyncMock())

        extra_fields = [
            {
                "name": "Field 1",
                "value": "Value 1",
                "inline": True,
            },
            {
                "name": "Field 2",
                "value": "Value 2",
                "inline": False,
            },
            # Field with no value should be skipped
            {
                "name": "Field 3",
                "value": None,
                "inline": False,
            },
        ]

        context = LogContext(
            log_message="Test with extra fields",
            log_channel=mock_channel,
            level="INFO",
            action="Extra Fields Test",
            embed=True,
            extra_embed_fields=extra_fields,
        )

        with caplog.at_level(logging.DEBUG):
            result = await DiscordBot._send_log_embed(context)

        mock_send.assert_called_once()
        embed = mock_send.call_args[1]["embed"]

        # Check that the debug log message was generated for each field
        assert len(caplog.records) >= 3  # At least 3 records (one for each field)
        assert any(
            "Parsing extra embed field" in record.message for record in caplog.records
        )

        # Check that fields with values were added to the embed
        assert len(embed.fields) >= 3  # Level field + 2 extra fields

        # Find the extra fields (they come after the Level field)
        extra_field_1 = None
        extra_field_2 = None

        for field in embed.fields:
            if field.name == "Field 1":
                extra_field_1 = field
            elif field.name == "Field 2":
                extra_field_2 = field

        assert extra_field_1 is not None
        assert extra_field_1.value == "Value 1"
        assert extra_field_1.inline is True

        assert extra_field_2 is not None
        assert extra_field_2.value == "Value 2"
        assert extra_field_2.inline is False

        # Ensure Field 3 was not added (it had no value)
        assert not any(field.name == "Field 3" for field in embed.fields)

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
    async def test_send_log_text_none_log_channel(self, mock_config: MagicMock) -> None:
        """Test that _send_log_text raises ValueError when log_channel is None."""
        # Temporarily set the LOG_CHANNEL to None
        mock_config.LOG_CHANNEL = None

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

        result = await DiscordBot._send_log_text(context)

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
        assert context.log_message == "**Bot event:** Test Event"
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
            context.log_message == "**Bot event:** Test Event\n**Details:** "
            "This is a test event with details"
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
        assert context.log_message == "**Bot event:** Warning Event"
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
        assert context.log_message == "**Bot event:** Channel Event"
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
            "**Bot event:** Critical Event\n**Details:** "
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
        assert call_args.user == mock_user  # Target user, not moderator
        assert mock_user.mention in call_args.log_message
        assert mock_mod.mention in call_args.log_message
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
        assert call_args.user == mock_user  # Target user, not moderator
        assert call_args.log_channel == mock_log_channel
        assert mock_user.mention in call_args.log_message
        assert mock_mod.mention in call_args.log_message
        assert reason in call_args.log_message
        assert call_args.embed is True

    @async_test
    async def test_log_moderation_action_with_message(
        self,
        mocker: MockerFixture,
        discord_bot: DiscordBot,
        mock_mod: MagicMock,
        mock_user: MagicMock,
        mock_message: MagicMock,
    ) -> None:
        """
        Test moderation action logging with message parameter and snippet creation.
        """
        action = "Ban"
        reason = "Inappropriate content"
        mock_log_to_channel = mocker.patch.object(
            discord_bot, "log_to_channel", AsyncMock(return_value="event_message")
        )

        # Test with a short message (less than max_msg_length)
        mock_message.content = "This is a short message"

        result = await discord_bot.log_moderation_action(
            moderator=mock_mod,
            target=mock_user,
            action=action,
            reason=reason,
            message=mock_message,
        )

        assert result == "event_message"
        mock_log_to_channel.assert_called_once()
        context = mock_log_to_channel.call_args[0][0]

        # Check that the message was added to extra_embed_fields
        assert len(context.extra_embed_fields) == 1
        message_field = context.extra_embed_fields[0]
        assert message_field["name"] == "Message"
        assert message_field["value"] == "This is a short message"
        assert message_field["inline"] is False

        # No ellipsis should be added for short messages
        assert "..." not in message_field["value"]

        # Reset mock for the next test
        mock_log_to_channel.reset_mock()

        # Test with a long message (more than max_msg_length)
        long_message = (
            "x" * 600
        )  # 600 characters, which exceeds the 500-character limit
        mock_message.content = long_message

        result = await discord_bot.log_moderation_action(
            moderator=mock_mod,
            target=mock_user,
            action=action,
            reason=reason,
            message=mock_message,
        )

        assert result == "event_message"
        mock_log_to_channel.assert_called_once()
        context = mock_log_to_channel.call_args[0][0]

        # Check that the message was truncated and ellipsis was added
        message_field = context.extra_embed_fields[0]
        assert message_field["name"] == "Message"
        assert message_field["value"] == long_message[:500] + "..."
        assert len(message_field["value"]) == 503  # 500 chars + 3 for ellipsis
        assert message_field["inline"] is False

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
            await discord_bot.ban_spammer("Test ban reason", mock_message)

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
            await discord_bot.ban_spammer("Test ban reason", mock_message)

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
            await discord_bot.ban_spammer("Test ban reason", mock_message)

        mocked_has_privileged_role.assert_called_once()
        mocked_log_to_channel.assert_called_once()
        assert len(caplog.records) == 2
        assert caplog.records[0].levelname == "INFO"
        assert (
            caplog.records[0].message
            == f"Processing potential spam from user {mock_user.display_name} "
            f"({mock_user}) in channel #{mock_message.channel.name}"
        )
        assert caplog.records[1].levelname == "INFO"
        assert (
            caplog.records[1].message
            == f"User {mock_user.display_name} ({mock_user}) has privileged role, "
            f"not banning"
        )

    @async_test
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
            await discord_bot.ban_spammer("Test ban reason", mock_message)

        mocked_has_privileged_role.assert_called_once()
        mocked_ban.assert_called_once()
        mocked_log_moderation_action.assert_called_once()
        assert len(caplog.records) == 3
        assert caplog.records[0].levelname == "INFO"
        assert (
            caplog.records[0].message
            == f"Processing potential spam from user {mock_user.display_name} "
            f"({mock_user}) in channel #{mock_message.channel.name}"
        )
        assert caplog.records[1].levelname == "WARNING"
        assert (
            caplog.records[1].message
            == f"Banning user {mock_user.display_name} ({mock_user}) for spam in "
            f"channel #{mock_message.channel.name}"
        )
        assert caplog.records[2].levelname == "WARNING"
        assert (
            caplog.records[2].message
            == f"Successfully banned user {mock_user.display_name} ({mock_user}) "
            f"for spam"
        )

    @async_test
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
            await discord_bot.ban_spammer("Test ban reason", mock_message)

        mocked_has_privileged_role.assert_called_once()
        mocked_ban.assert_called_once()
        mocked_log_error.assert_called_once()

        # Check log messages
        assert len(caplog.records) == 3
        assert caplog.records[0].levelname == "INFO"
        assert (
            caplog.records[0].message
            == f"Processing potential spam from user {mock_user.display_name} "
            f"({mock_user}) in channel #{mock_message.channel.name}"
        )
        assert caplog.records[1].levelname == "WARNING"
        assert (
            caplog.records[1].message
            == f"Banning user {mock_user.display_name} ({mock_user}) for spam in "
            f"channel #{mock_message.channel.name}"
        )
        assert caplog.records[2].levelname == "ERROR"
        assert "Bot lacks permission to ban user" in caplog.records[2].message

    @async_test
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
            await discord_bot.ban_spammer("Test ban reason", mock_message)

        mocked_has_privileged_role.assert_called_once()
        mocked_ban.assert_called_once()
        mocked_log_error.assert_called_once()

        # Check log messages
        assert len(caplog.records) == 3
        assert caplog.records[0].levelname == "INFO"
        assert (
            caplog.records[0].message
            == f"Processing potential spam from user {mock_user.display_name} "
            f"({mock_user}) in channel #{mock_message.channel.name}"
        )
        assert caplog.records[1].levelname == "WARNING"
        assert (
            caplog.records[1].message
            == f"Banning user {mock_user.display_name} ({mock_user}) for spam in "
            f"channel #{mock_message.channel.name}"
        )
        assert caplog.records[2].levelname == "ERROR"
        assert "HTTP error while banning user" in caplog.records[2].message

    @async_test
    async def test_on_ready(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_config: MagicMock,
    ) -> None:
        """Test the on_ready method"""
        mocker.patch.object(
            discord_bot, "_get_log_channel", return_value=mock_config.LOG_CHANNEL
        )
        mock_log_bot_event = mocker.patch("lib.bot.DiscordBot.log_bot_event")
        mock_load_cogs = mocker.patch.object(discord_bot, "_load_cogs")

        with caplog.at_level(logging.INFO):
            await discord_bot.on_ready()

        assert len(caplog.records) == 2
        assert caplog.records[0].levelname == "INFO"
        assert "We have logged in as TestBot" in caplog.records[0].message
        assert caplog.records[1].levelname == "INFO"
        assert "Registered commands:" in caplog.records[1].message
        mock_load_cogs.assert_called_once()
        mock_log_bot_event.assert_called_once()

    @async_test
    async def test_on_ready_no_user(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: MagicMock,
        mock_config: MagicMock,
    ) -> None:
        """Test the on_ready method when the bot has no user"""
        mocker.patch.object(type(discord_bot), "user", None)
        mocker.patch.object(
            discord_bot, "_get_log_channel", return_value=mock_config.LOG_CHANNEL
        )
        mock_load_cogs = mocker.patch.object(discord_bot, "_load_cogs")
        mock_log_bot_event = mocker.patch("lib.bot.DiscordBot.log_bot_event")

        with caplog.at_level(logging.INFO):
            await discord_bot.on_ready()

        # Verify that the error message is logged when self.user is None
        assert len(caplog.records) == 2
        assert caplog.records[0].levelname == "ERROR"
        assert "The bot user is not set" in caplog.records[0].message
        assert caplog.records[1].levelname == "INFO"
        assert "Registered commands:" in caplog.records[1].message

        mock_load_cogs.assert_called_once()
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
        mock_load_cogs = mocker.patch.object(discord_bot, "_load_cogs")

        with caplog.at_level(logging.INFO):
            await discord_bot.on_ready()

        assert len(caplog.records) == 3
        assert caplog.records[0].levelname == "INFO"
        assert "We have logged in as TestBot" in caplog.records[0].message
        assert caplog.records[1].levelname == "WARNING"
        assert (
            f"Could not find log channel with ID {mock_config.CHANNELS.BOT_LOGS}"
            in caplog.records[1].message
        )
        assert caplog.records[2].levelname == "INFO"
        assert "Registered commands:" in caplog.records[2].message
        mock_load_cogs.assert_called_once()
        mock_log_bot_event.assert_called_once()

    @async_test
    async def test_on_ready_no_match(
        self, mocker: MockerFixture, discord_bot: MagicMock, mock_message: MagicMock
    ) -> None:
        """Test the case where no conditions are matched"""
        mock_ban_spammer = mocker.patch("lib.bot.DiscordBot.ban_spammer")
        mock_process_commands = mocker.patch("lib.bot.DiscordBot.process_commands")

        await discord_bot.on_message(mock_message)

        mock_ban_spammer.assert_not_called()
        mock_process_commands.assert_called_once()

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
        assert (
            record.message
            == f"Received message from {mock_user.display_name} ({mock_user}) "
            f"in #mousetrap: {mock_message.content}"
        )

    async def test_on_member_join(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_channel: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test the on_member_join method with a valid rules channel"""
        mocked_get_channel = mocker.patch.object(
            discord_bot, "get_channel", return_value=mock_channel
        )

        with caplog.at_level(logging.INFO):
            await discord_bot.on_member_join(mock_user)

        mocked_get_channel.assert_called_once()
        mock_user.send.assert_called_once()
        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "INFO"
        assert (
            caplog.records[0].message
            == f"Member {mock_user.display_name} ({mock_user}) joined the server"
        )

    async def test_on_member_join_no_rules_channel(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_user: MagicMock,
    ) -> None:
        """Test the on_member_join method when the #rules channel is not found"""
        # Mock get_channel to return None (channel not found)
        mocked_get_channel = mocker.patch.object(
            discord_bot, "get_channel", return_value=None
        )

        with caplog.at_level(logging.WARNING):
            await discord_bot.on_member_join(mock_user)

        mocked_get_channel.assert_called_once()

        # Verify the embed was created without channel mention
        # We need to inspect the call arguments to verify the embed content
        mock_user.send.assert_called_once()
        call_args = mock_user.send.call_args[1]
        embed = call_args["embed"]

        # Check that the embed has the expected content
        assert embed.title == "Welcome to the Jim's Garage server!"
        assert "Welcome to the server" in embed.description
        assert "rules channel" in embed.description  # Generic reference without mention
        assert embed.color == discord.Color.blue()

        # Verify warning was logged
        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "WARNING"
        assert "Could not find rules channel" in caplog.records[0].message

    async def test_on_member_join_dm_forbidden(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_channel: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test the on_member_join method when DM fails with a Forbidden exception"""
        # Mock get_channel to return a valid channel
        mocker.patch.object(discord_bot, "get_channel", return_value=mock_channel)

        # Mock member.send to raise discord.Forbidden
        mock_user.send.side_effect = discord.Forbidden(
            response=MagicMock(), message="Cannot send messages to this user"
        )

        with caplog.at_level(logging.WARNING):
            await discord_bot.on_member_join(mock_user)

        # Verify send was attempted
        mock_user.send.assert_called_once()

        # Verify warning was logged
        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "WARNING"
        assert "Could not send welcome message" in caplog.records[0].message
        assert "DMs may be disabled" in caplog.records[0].message

    async def test_on_member_join_dm_http_exception(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        mock_channel: MagicMock,
        mock_user: MagicMock,
    ) -> None:
        """Test the on_member_join method when DM fails with HTTPException"""
        # Mock get_channel to return a valid channel
        mocker.patch.object(discord_bot, "get_channel", return_value=mock_channel)

        # Create an HTTP exception with a specific error message
        http_error = "Internal Server Error"
        mock_user.send.side_effect = discord.HTTPException(
            response=MagicMock(), message=http_error
        )

        with caplog.at_level(logging.WARNING):
            await discord_bot.on_member_join(mock_user)

        # Verify send was attempted
        mock_user.send.assert_called_once()

        # Verify warning was logged
        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "WARNING"
        assert "Failed to send welcome message" in caplog.records[0].message
        assert http_error in caplog.records[0].message

    @async_test
    async def test_load_cogs_directory_not_exists(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
    ) -> None:
        """Test _load_cogs when the cogs directory doesn't exist."""
        # Mock Path.exists() to return False
        mock_path = mocker.patch("lib.bot.Path")
        mock_path.return_value.exists.return_value = False

        with caplog.at_level(logging.WARNING):
            await discord_bot._load_cogs()

        assert len(caplog.records) == 1
        assert caplog.records[0].levelname == "WARNING"
        assert "Cogs directory 'lib/cogs' does not exist" in caplog.records[0].message

    @async_test
    async def test_load_cogs_skip_dunder_files(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
    ) -> None:
        """Test _load_cogs skips files starting with '__'."""
        # Mock Path and its methods
        mock_path = mocker.patch("lib.bot.Path")
        mock_cogs_dir = mock_path.return_value
        mock_cogs_dir.exists.return_value = True

        # Create mock files including __init__.py
        mock_init_file = MagicMock()
        mock_init_file.name = "__init__.py"
        mock_init_file.stem = "__init__"

        mock_regular_file = MagicMock()
        mock_regular_file.name = "test_cog.py"
        mock_regular_file.stem = "test_cog"

        mock_cogs_dir.glob.return_value = [mock_init_file, mock_regular_file]

        # Track calls to importlib.import_module for cog modules specifically
        original_import: Callable[[str], ModuleType] = importlib.import_module
        cog_import_calls: list[str] = []

        def import_side_effect(name: str) -> ModuleType:
            if name.startswith("lib.cogs."):
                cog_import_calls.append(name)
                return MagicMock()
            return original_import(name)

        mocker.patch("lib.bot.importlib.import_module", side_effect=import_side_effect)

        # Mock dir() to return empty list (no cog classes)
        mocker.patch("lib.bot.dir", return_value=[])

        with caplog.at_level(logging.WARNING):
            await discord_bot._load_cogs()

        # Verify __init__.py was skipped (import_module called only once for test_cog)
        assert cog_import_calls == ["lib.cogs.test_cog"]

        # Verify warning logged for no cog class found
        assert any(
            "No valid Cog class found" in record.message for record in caplog.records
        )

    @async_test
    async def test_load_cogs_successful_loading(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
    ) -> None:
        """Test _load_cogs successfully loads a valid cog."""
        # Mock Path and its methods
        mock_path = mocker.patch("lib.bot.Path")
        mock_cogs_dir = mock_path.return_value
        mock_cogs_dir.exists.return_value = True

        mock_file = MagicMock()
        mock_file.name = "test_cog.py"
        mock_file.stem = "test_cog"
        mock_cogs_dir.glob.return_value = [mock_file]

        original_import: Callable[[str], ModuleType] = importlib.import_module

        def import_side_effect(name: str) -> ModuleType:
            if name.startswith("lib.cogs."):
                return MagicMock()
            return original_import(name)

        mocker.patch("lib.bot.importlib.import_module", side_effect=import_side_effect)

        # Create a mock Cog class
        mock_cog_class = MagicMock()
        mock_cog_class.__name__ = "TestCog"
        mock_cog_class.__bases__ = (commands.Cog,)
        mock_cog_instance = MagicMock()
        mock_cog_class.return_value = mock_cog_instance

        # Mock dir() to return the cog class
        mocker.patch("lib.bot.dir", return_value=["TestCog"])
        # Mock getattr to return our mock cog class
        mocker.patch("lib.bot.getattr", return_value=mock_cog_class)
        # Mock isinstance and issubclass
        mocker.patch("lib.bot.isinstance", return_value=True)
        mocker.patch("lib.bot.issubclass", return_value=True)

        # Mock add_cog method
        mock_add_cog = mocker.patch.object(discord_bot, "add_cog", AsyncMock())

        with caplog.at_level(logging.INFO):
            await discord_bot._load_cogs()

        # Verify cog was loaded
        mock_cog_class.assert_called_once_with(discord_bot)
        mock_add_cog.assert_called_once_with(mock_cog_instance)

        # Verify success logs
        assert any(
            "Loaded cog: TestCog from lib.cogs.test_cog" in record.message
            for record in caplog.records
        )
        assert any(
            "Successfully loaded 1 cogs: TestCog" in record.message
            for record in caplog.records
        )

    @async_test
    async def test_load_cogs_no_valid_cog_class(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
    ) -> None:
        """Test _load_cogs when a module has no valid Cog class."""
        # Mock Path and its methods
        mock_path = mocker.patch("lib.bot.Path")
        mock_cogs_dir = mock_path.return_value
        mock_cogs_dir.exists.return_value = True

        mock_file = MagicMock()
        mock_file.name = "invalid_cog.py"
        mock_file.stem = "invalid_cog"
        mock_cogs_dir.glob.return_value = [mock_file]

        # Mock importlib.import_module
        mock_import = mocker.patch("lib.bot.importlib.import_module")
        mock_module = MagicMock()
        mock_import.return_value = mock_module

        # Mock dir() to return some attributes but none are valid cogs
        mocker.patch("lib.bot.dir", return_value=["SomeClass", "some_function"])

        # Mock getattr and isinstance/issubclass to return invalid cog
        def mock_getattr_side_effect(name: str) -> MagicMock:
            if name == "SomeClass":
                return MagicMock()
            return MagicMock()

        mocker.patch("lib.bot.getattr", side_effect=mock_getattr_side_effect)
        mocker.patch("lib.bot.isinstance", return_value=False)

        with caplog.at_level(logging.WARNING):
            await discord_bot._load_cogs()

        # Verify warning logged for no valid cog class
        assert any(
            "No valid Cog class found in lib.cogs.invalid_cog" in record.message
            for record in caplog.records
        )
        assert any(
            "Failed to load 1 cogs: invalid_cog" in record.message
            for record in caplog.records
        )

    @async_test
    @pytest.mark.parametrize(
        ("exception", "exception_type"),
        [
            (ImportError("Module not found"), ImportError),
            (ModuleNotFoundError("No module named"), ModuleNotFoundError),
            (AttributeError("Attribute error"), AttributeError),
            (TypeError("Type error"), TypeError),
            (discord.ClientException("Discord client error"), discord.ClientException),
        ],
    )
    async def test_load_cogs_import_exceptions(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
        exception: Exception,
        exception_type: type[Exception],
    ) -> None:
        """Test _load_cogs handles various import exceptions."""
        # Mock Path and its methods
        mock_path = mocker.patch("lib.bot.Path")
        mock_cogs_dir = mock_path.return_value
        mock_cogs_dir.exists.return_value = True

        mock_file = MagicMock()
        mock_file.name = "broken_cog.py"
        mock_file.stem = "broken_cog"
        mock_cogs_dir.glob.return_value = [mock_file]

        original_import: Callable[[str], ModuleType] = importlib.import_module

        def import_side_effect(name: str) -> ModuleType:
            if name.startswith("lib.cogs."):
                raise exception
            return original_import(name)

        mocker.patch("lib.bot.importlib.import_module", side_effect=import_side_effect)

        with caplog.at_level(logging.WARNING):
            await discord_bot._load_cogs()

        # Verify exception was logged
        assert any(
            "Failed to load cog from lib.cogs.broken_cog" in record.message
            for record in caplog.records
        )
        assert any(
            "Failed to load 1 cogs: broken_cog" in record.message
            for record in caplog.records
        )
        assert isinstance(exception, exception_type)

    @async_test
    async def test_load_cogs_mixed_results(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
    ) -> None:
        """Test _load_cogs with mixed successful and failed cog loading."""
        # Mock Path and its methods
        mock_path = mocker.patch("lib.bot.Path")
        mock_cogs_dir = mock_path.return_value
        mock_cogs_dir.exists.return_value = True

        # Create multiple mock files
        mock_good_file = MagicMock()
        mock_good_file.name = "good_cog.py"
        mock_good_file.stem = "good_cog"

        mock_bad_file = MagicMock()
        mock_bad_file.name = "bad_cog.py"
        mock_bad_file.stem = "bad_cog"

        mock_dunder_file = MagicMock()
        mock_dunder_file.name = "__pycache__"
        mock_dunder_file.stem = "__pycache__"

        mock_cogs_dir.glob.return_value = [
            mock_good_file,
            mock_bad_file,
            mock_dunder_file,
        ]

        original_import: Callable[[str], ModuleType] = importlib.import_module

        def import_side_effect(module_name: str) -> ModuleType:
            if module_name.startswith("lib.cogs."):
                if "good_cog" in module_name:
                    return MagicMock()
                if "bad_cog" in module_name:
                    msg = "Failed to import"
                    raise ImportError(msg)
                return MagicMock()
            return original_import(module_name)

        mocker.patch("lib.bot.importlib.import_module", side_effect=import_side_effect)

        # Mock successful cog loading for good_cog
        def dir_side_effect(_module: object) -> list[str]:
            return ["GoodCog"]

        def getattr_side_effect(_module: object, _attr_name: str) -> MagicMock:
            mock_cog_class = MagicMock()
            mock_cog_class.__name__ = "GoodCog"
            mock_cog_class.__bases__ = (commands.Cog,)
            return mock_cog_class

        mocker.patch("lib.bot.dir", side_effect=dir_side_effect)
        mocker.patch("lib.bot.getattr", side_effect=getattr_side_effect)
        mocker.patch("lib.bot.isinstance", return_value=True)
        mocker.patch("lib.bot.issubclass", return_value=True)

        # Mock add_cog method
        mock_add_cog = mocker.patch.object(discord_bot, "add_cog", AsyncMock())

        with caplog.at_level(logging.INFO):
            await discord_bot._load_cogs()

        mock_add_cog.assert_called_once()

        # Verify both success and failure logs
        assert any(
            "Loaded cog: GoodCog from lib.cogs.good_cog" in record.message
            for record in caplog.records
        )
        assert any(
            "Successfully loaded 1 cogs: GoodCog" in record.message
            for record in caplog.records
        )
        assert any(
            "Failed to load cog from lib.cogs.bad_cog" in record.message
            for record in caplog.records
        )
        assert any(
            "Failed to load 1 cogs: bad_cog" in record.message
            for record in caplog.records
        )

    @async_test
    async def test_load_cogs_no_cogs_to_load(
        self,
        mocker: MockerFixture,
        caplog: pytest.LogCaptureFixture,
        discord_bot: DiscordBot,
    ) -> None:
        """Test _load_cogs when the directory exists but has no Python files."""
        # Mock Path and its methods
        mock_path = mocker.patch("lib.bot.Path")
        mock_cogs_dir = mock_path.return_value
        mock_cogs_dir.exists.return_value = True
        mock_cogs_dir.glob.return_value = []  # No files found

        with caplog.at_level(logging.INFO):
            await discord_bot._load_cogs()

        # Should complete without any logging since no cogs were loaded or failed
        assert not any(
            "Successfully loaded" in record.message for record in caplog.records
        )
        assert not any("Failed to load" in record.message for record in caplog.records)
