import asyncio
import calendar
import datetime
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from lib.config import config

if TYPE_CHECKING:
    from lib.bot import DiscordBot  # noqa: F401 RUF100 - used in type annotations

logger: logging.Logger = logging.getLogger(__name__)


class Tasks(commands.Cog):
    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot
        self.clean_channel_members.start()

    async def cog_unload(self) -> None:
        self.clean_channel_members.cancel()

    @tasks.loop(time=datetime.time(hour=17, minute=0, second=0, tzinfo=config.TIMEZONE))
    async def clean_channel_members(self) -> None:
        """
        Kick all members that joined over 1 week ago and do not have the
        Garage Member role (meaning they have not accepted the rules).

        Run each Sunday at 1700 UTC.
        """
        if datetime.datetime.now(tz=config.TIMEZONE).weekday() == calendar.SUNDAY:
            if not (guild := self.bot.get_guild(config.GUILDS.JIMS_GARAGE)):
                msg = f"Guild with ID {config.GUILDS.JIMS_GARAGE} not found"
                raise ValueError(msg)
            logger.info("Cleaning channel members for %s (%s)", guild.name, guild.id)
            await self.bot.log_bot_event(event="Task - Member Cleanup")

            count = 0

            for member in guild.members:
                if not (joined_time := member.joined_at):
                    continue
                if (
                    not any(role.id == config.ROLES.BOTS for role in member.roles)
                    and not any(
                        role.id == config.ROLES.GARAGE_MEMBER for role in member.roles
                    )
                    and (datetime.datetime.now(tz=config.TIMEZONE) - joined_time)
                    > datetime.timedelta(weeks=1)
                ):
                    # Sleep to safely avoid rate limiting (50 requests per second)
                    await asyncio.sleep(0.2)

                    # Send DM before kicking
                    try:
                        await member.send(
                            "You have been removed from the Jim's Garage server "
                            "because you joined over a week ago and haven't accepted "
                            "the rules. If you believe this was a mistake, please "
                            "feel free to rejoin the server and reach out to a mod."
                        )
                        logger.info(
                            "Sent DM to %s (%s) before kicking",
                            member.display_name,
                            member,
                        )
                    except discord.Forbidden:
                        logger.warning(
                            "Could not send DM to %s (%s) - "
                            "DMs may be disabled or bot is blocked",
                            member.display_name,
                            member,
                        )
                    except discord.HTTPException as e:
                        logger.warning(
                            "Failed to send DM to %s: %s", member.display_name, e
                        )

                    await member.kick(
                        reason="Member has not accepted the rules in over a week."
                    )
                    logger.info(
                        "Kicked %s (%s) from the server - joined %s - roles: %s",
                        member.display_name,
                        member,
                        joined_time.strftime("%Y-%m-%d %H:%M")
                        if member.joined_at
                        else "Unknown",
                        member.roles,
                    )
                    count += 1

            logger.info("Cleaned %s members.", count)
            await self.bot.log_bot_event(
                event="Task - Member Cleanup",
                details=f"Cleaned {count} members.",
            )

    @clean_channel_members.before_loop
    async def before_clean_channel_members(self) -> None:
        """Called before the task loop starts"""
        logger.info("clean_channel_members task is starting up...")
        await self.bot.wait_until_ready()  # Wait for bot to be ready before starting
