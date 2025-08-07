"""DiscordBot class"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, tzinfo  # noqa: F401 RUF100 - used in cast() as string
from typing import cast

import discord

from lib.config import config

logger: logging.Logger = logging.getLogger(__name__)

EmbedFieldDict = dict[str, bool | str | None] | dict[str, bool | str]


@dataclass
class LogContext:
    """Context information for logging"""

    log_message: str
    log_channel: discord.TextChannel | None = None
    level: str = "INFO"
    color: discord.Color | None = None
    action: str | None = None
    embed: bool = False
    user: discord.Member | discord.ClientUser | None = None
    channel: discord.TextChannel | None = None
    extra_embed_fields: list[EmbedFieldDict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.color:
            self.color = self._get_level_color(self.level)
        if not self.log_channel:
            if DiscordBot.default_log_channel:
                self.log_channel = DiscordBot.default_log_channel
                logger.debug("Using default log channel")
            else:
                msg = "Logging channel not found."
                raise AttributeError(msg)

    @staticmethod
    def _get_level_color(level: str) -> discord.Color:
        """Get color based on the log level"""
        level_colors = {
            "CRITICAL": discord.Color.dark_red(),
            "ERROR": discord.Color.red(),
            "WARNING": discord.Color.orange(),
            "INFO": discord.Color.blue(),
            "DEBUG": discord.Color.light_grey(),
        }
        return level_colors.get(level.upper(), discord.Color.default())


class DiscordBot(discord.Client):
    """Discord bot class"""

    default_log_channel: discord.TextChannel | None = None

    async def on_ready(self) -> None:
        """Called when the bot is ready"""
        logger.info("We have logged in as %s", self.user)

        # Initialize the global default_log_channel
        # global default_log_channel
        DiscordBot.default_log_channel = await self._get_log_channel()
        if not DiscordBot.default_log_channel:
            logger.warning(
                "Could not find log channel with ID %s", config.CHANNELS.BOT_LOGS
            )

        await self.log_bot_event(
            level="INFO", event="Bot Startup", details=f"Version {config.VERSION}"
        )

    async def close(self) -> None:
        await asyncio.wait_for(
            self.log_bot_event(
                event="Bot Shutdown",
                details=f"Version {config.VERSION} shutting down",
                level="WARNING",
            ),
            timeout=3.0,
        )
        try:
            await super().close()
        except (
            discord.ConnectionClosed,
            RuntimeError,
            asyncio.CancelledError,
            OSError,
        ) as e:
            logger.warning("Error during close: %s", e)

    async def _get_log_channel(self) -> discord.TextChannel | None:
        """Get the log channel"""
        bot_logs_channel = self.get_channel(config.CHANNELS.BOT_LOGS) or None
        if bot_logs_channel is not None and not isinstance(
            bot_logs_channel, discord.TextChannel
        ):
            logger.warning(
                "BOT_LOGS channel ID %s is not a TextChannel (got %s)",
                config.CHANNELS.BOT_LOGS,
                type(bot_logs_channel).__name__,
            )
            return None
        return bot_logs_channel

    @staticmethod
    async def _send_log_embed(context: LogContext) -> discord.Message:
        """Send log as a formatted embed"""

        embed = discord.Embed(
            title=context.action or f"{context.level} Log",
            description=context.log_message,
            color=context.color,
            timestamp=datetime.now(tz=cast("tzinfo", config.TIMEZONE)),
        )

        if context.user:
            embed.add_field(
                name="User",
                value=f"{context.user.mention}\n`{context.user.id}`",
                inline=True,
            )

        if context.channel:
            embed.add_field(
                name="Channel",
                value=f"{context.channel.mention}\n`{context.channel.id}`",
                inline=True,
            )

        embed.add_field(name="Level", value=context.level, inline=True)

        for embed_field in context.extra_embed_fields:
            logger.debug("Parsing extra embed field: %s", field)
            if embed_field.get("value"):
                embed.add_field(
                    name=embed_field.get("name", "Missing embed name"),
                    value=embed_field.get("value", "Missing embed value"),
                    inline=bool(embed_field.get("inline", False)),
                )

        logger.info("Sending embed log message: %s", embed.to_dict())

        if context.log_channel is None:
            msg = "Cannot send log message: log_channel is None"
            raise ValueError(msg)
        return await context.log_channel.send(embed=embed)

    @staticmethod
    async def _send_log_text(context: LogContext) -> discord.Message:
        """Send log as a formatted text message"""
        timestamp = datetime.now(cast("tzinfo", config.TIMEZONE)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        log_parts = [f"[{timestamp}] [{context.level}]"]

        if context.action:
            log_parts.append(f"**{context.action}**")

        log_parts.append(context.log_message)

        if context.user:
            log_parts.append(f"| User: {context.user.mention} ({context.user.id})")

        if context.channel:
            log_parts.append(
                f"| Channel: {context.channel.mention} ({context.channel.id})"
            )

        log_message = " ".join(log_parts)
        logger.info("Sending text log message: %s", log_message)
        if context.log_channel is None:
            msg = "Cannot send log message: log_channel is None"
            raise ValueError(msg)
        return await context.log_channel.send(log_message)

    async def log_to_channel(self, context: LogContext) -> discord.Message | None:
        """
        Send a log message to the context.log_channel.

        Returns:
            The message that was sent or None if failed
        """
        try:
            if context.embed:
                return await self._send_log_embed(context)
            return await self._send_log_text(context)

        except discord.HTTPException:
            logger.exception("Failed to send log message")
            return None

    # Convenience methods for different log levels
    async def log_critical(self, context: LogContext) -> discord.Message | None:
        """Log a critical message"""
        context.level = "CRITICAL"
        return await self.log_to_channel(context)

    async def log_error(self, context: LogContext) -> discord.Message | None:
        """Log an error message"""
        context.level = "ERROR"
        return await self.log_to_channel(context)

    async def log_warning(self, context: LogContext) -> discord.Message | None:
        """Log a warning message"""
        context.level = "WARNING"
        return await self.log_to_channel(context)

    async def log_info(self, context: LogContext) -> discord.Message | None:
        """Log an info message"""
        context.level = "INFO"
        return await self.log_to_channel(context)

    async def log_debug(self, context: LogContext) -> discord.Message | None:
        """Log a debug message"""
        context.level = "DEBUG"
        return await self.log_to_channel(context)

    async def log_bot_event(
        self,
        event: str,
        level: str = "INFO",
        details: str = "",
        log_channel: discord.TextChannel | None = None,
    ) -> discord.Message | None:
        """Log a bot-related event"""
        context = LogContext(
            log_message=f"**Bot event:** {event}",
            level=level,
            action="Bot Event",
            embed=True,
        )
        if details:
            context.log_message += f"\n**Details:** {details}"
        if log_channel:
            context.log_channel = log_channel

        return await self.log_to_channel(context)

    async def log_moderation_action(  # noqa: PLR0913
        self,
        moderator: discord.Member | discord.ClientUser,
        target: discord.Member | discord.ClientUser,
        action: str,
        reason: str = "No reason provided",
        extra_log_channel: discord.TextChannel | None = None,
        channel: discord.TextChannel | None = None,
        level: str = "WARNING",
        message: discord.Message | None = None,
    ) -> discord.Message | None:
        """
        Log a moderation action.
        Specify log_channel to duplicate log to a public channel
        """
        message_snippet = None
        if message:
            max_msg_length = 500
            message_snippet = (
                f"{message.content[:max_msg_length]}"
                f"{'...' if len(message.content) > max_msg_length else ''}"
            )

        context = LogContext(
            action=f"Moderation: {action}",
            log_message=(
                f"**{action}** performed on {target.mention} by {moderator.mention}\n"
                f"**Reason:** {reason}"
            ),
            embed=True,
            user=target,
            channel=channel,
            level=level,
            extra_embed_fields=[
                {
                    "name": "Message",
                    "value": message_snippet if message else None,
                    "inline": False,
                },
            ],
        )
        if extra_log_channel:
            context.log_channel = extra_log_channel
            await self.log_to_channel(context)
        context.log_channel = self.default_log_channel
        return await self.log_to_channel(context)

    async def log_user_action(
        self,
        user: discord.Member,
        action: str,
        details: str = "",
        log_channel: discord.TextChannel | None = None,
    ) -> discord.Message | None:
        """Log a user action"""
        context = LogContext(
            log_channel=log_channel,
            log_message=f"**{action}** performed by {user.mention}",
            level="INFO",
            action=f"User Action: {action}",
            embed=True,
            user=user,
        )
        if details:
            context.log_message += f"\nDetails: {details}"

        return await self.log_to_channel(context)

    @staticmethod
    def _has_privileged_role(member: discord.Member) -> bool:
        """Check if a member has admin, mod, or Jim's Garage roles"""
        logger.debug("Checking if user %s has privileged roles", member)
        privileged_role_ids = {
            config.ROLES.ADMIN,
            config.ROLES.JIMS_GARAGE,
            config.ROLES.MOD,
        }

        user_role_ids = {role.id for role in member.roles}
        logger.debug("User role IDs: %s", user_role_ids)
        return bool(privileged_role_ids & user_role_ids)

    async def ban_spammer(self, ban_reason: str, message: discord.Message) -> None:
        """
        Ban users due to spam.
        Check user privileges so the bot does not ban admins, mods, etc.

        Args:
            ban_reason: The reason for the ban
            message: The message that triggered the spam detection
        """
        if not isinstance(message.author, discord.Member):
            logger.warning(
                "Message author is not a Member object, skipping `ban_spammer`."
            )
            return

        # TODO @cyberops7: test if this needs to include discord.Thread as well
        if not isinstance(message.channel, discord.TextChannel):
            logger.warning(
                "Message channel is not a TextChannel, skipping `ban_spammer`"
            )
            return

        user: discord.Member = message.author
        channel: discord.TextChannel = message.channel

        logger.info(
            "Processing potential spam from user %s (%s) in channel #%s",
            user.display_name,
            user,
            channel.name,
        )

        # Check if the user has privileged roles
        if self._has_privileged_role(user):
            logger.info(
                "User %s (%s) has privileged role, not banning",
                user.display_name,
                user,
            )

            # Log the privileged user attempt
            max_msg_length = 100
            await self.log_to_channel(
                context=LogContext(
                    log_message=(
                        f"Privileged user {user.mention} triggered spam detection in "
                        f"#{channel.name}, but was not banned.\n"
                        f"**Message:** {message.content[:max_msg_length]}{
                            '...' if len(message.content) > max_msg_length else ''
                        }\n"
                        f"**Roles:** {
                            ', '.join(
                                role.name
                                for role in user.roles
                                if role.name != '@everyone'
                            )
                        }"
                    ),
                    level="WARNING",
                    action="Spam Detection - Privileged User",
                    embed=True,
                    user=user,
                    channel=channel,
                )
            )
            return

        # User does not have privileged roles, proceed with the ban
        logger.warning(
            "Banning user %s (%s) for spam in channel #%s",
            user.display_name,
            user,
            channel.name,
        )

        # Ban the user
        try:
            await user.ban(reason=ban_reason, delete_message_days=1)
            logger.warning(
                "Successfully banned user %s (%s) for spam",
                user.display_name,
                user,
            )

            # Log the successful ban
            # TODO @cyberops7: also log to #general-chat
            await self.log_moderation_action(
                moderator=cast("discord.ClientUser", self.user),  # Bot as moderator
                target=user,
                action="Ban",
                reason=f"{ban_reason}\nDeleted messages from {user.display_name}"
                f"({user}) from the last day.",
                channel=channel,
                level="CRITICAL",
                message=message,
            )

        except discord.Forbidden:
            logger.exception(
                "Bot lacks permission to ban user %s (%s)",
                user.display_name,
                user,
            )

            # Log the permission error
            await self.log_error(
                context=LogContext(
                    log_message=(
                        f"Failed to ban user {user.mention} - "
                        f"insufficient permissions.\n"
                        f"**Reason:** {ban_reason}"
                    ),
                    level="ERROR",
                    action="Ban Failed - Permissions",
                    embed=True,
                    user=user,
                    channel=channel,
                )
            )

        except discord.HTTPException as e:
            logger.exception(
                "HTTP error while banning user %s (%s)",
                user.display_name,
                user.id,
            )

            # Log the HTTP error
            await self.log_error(
                context=LogContext(
                    log_message=(
                        f"Failed to ban user {user.mention} - "
                        f"HTTP error.\n**Error:** {e}\n"
                        f"**Reason:** {ban_reason}"
                    ),
                    level="ERROR",
                    action="Ban Failed - HTTP Error",
                    embed=True,
                    user=user,
                    channel=channel,
                )
            )

    async def on_message(self, message: discord.Message) -> None:
        """Called when a message is received"""
        # Ignore messages from the bot itself
        if message.author == self.user:
            return

        # Ban spammers - no one is supposed to post to #mousetrap
        if message.channel.id == config.CHANNELS.MOUSETRAP:
            logger.warning(
                "Received message from %s (%s) in #mousetrap: %s",
                message.author.display_name,
                message.author,
                message.content,
            )
            ban_reason = "Message detected in #mousetrap."
            await self.ban_spammer(ban_reason, message)

        if message.channel.id == config.CHANNELS.BOT_PLAYGROUND:
            # Respond to messages starting with "hello"
            if message.content.lower().startswith("hello"):
                logger.info("Received 'hello' from %s", message.author)
                await message.channel.send("Hello")
                return
            if message.content.lower().startswith("ping"):
                logger.info("Received 'ping' from %s", message.author)
                await message.channel.send("Pong")
                return

    async def on_member_join(self, member: discord.Member) -> None:
        """Called when a member joins the server"""
        logger.info("Member %s (%s) joined the server", member.display_name, member)
        rules_channel = self.get_channel(config.CHANNELS.RULES)

        # Type check and ensure it is a TextChannel (makes pyre happy)
        if not rules_channel or not isinstance(rules_channel, discord.TextChannel):
            logger.warning(
                "Could not find rules channel with ID %s or it is not a TextChannel",
                config.CHANNELS.RULES,
            )
            # Fallback message without channel mention
            embed = discord.Embed(
                title="Welcome to the Jim's Garage server!",
                description=(
                    f"Welcome to the server, {member.mention}! "
                    f"Please read the rules in the rules channel. "
                    f"You will need to react to the first post in that channel with "
                    f":white_check_mark: to gain access to the rest of the channels.\n"
                    f"<:logo_small1:1181558525202284585>"
                ),
                color=discord.Color.blue(),
            )
        else:
            embed = discord.Embed(
                title="Welcome to the Jim's Garage server!",
                description=(
                    f"Welcome to the server, {member.mention}! "
                    f"Please read the rules in {rules_channel.mention}. "
                    f"You will need to react to the first post in that channel with "
                    f":white_check_mark: to gain access to the rest of the channels.\n"
                    f"<:logo_small1:1181558525202284585>"
                ),
                color=discord.Color.blue(),
            )

        try:
            await member.send(embed=embed)
        except discord.Forbidden:
            logger.warning(
                "Could not send welcome message to %s - DMs may be disabled",
                member.display_name,
            )
        except discord.HTTPException as e:
            logger.warning(
                "Failed to send welcome message to %s: %s", member.display_name, e
            )
