import asyncio
import calendar
import datetime
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks
from feedparser import FeedParserDict

from lib import youtube
from lib.config import config

if TYPE_CHECKING:
    from lib.bot import DiscordBot  # noqa: F401 RUF100 - used in type annotations

logger: logging.Logger = logging.getLogger(__name__)


class Tasks(commands.Cog):
    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot

        # TODO @cyberops7: refactor the startup code into a separate function
        # Bootstrap task: Clean Channel Members
        if config.DRY_RUN:
            if not self.clean_channel_members_task_dry_run.is_running():
                self.clean_channel_members_task_dry_run.start()
            else:
                logger.warning(
                    "clean_channel_members_task_dry_run task is already running"
                )
        elif not self.clean_channel_members_task.is_running():
            self.clean_channel_members_task.start()
        else:
            logger.warning("clean_channel_members_task task is already running")

        # Bootstrap task: YouTube Video Monitor
        if not self.monitor_youtube_videos.is_running():
            self.youtube_feeds: dict[str, youtube.YoutubeFeedParser] = {}
            self.monitor_youtube_videos.start()
        else:
            logger.warning("monitor_youtube_videos task is already running")

    async def cog_unload(self) -> None:
        # Close task: Clean Channel Members
        if config.DRY_RUN:
            self.clean_channel_members_task_dry_run.cancel()
        else:
            self.clean_channel_members_task.cancel()

        # Close task: YouTube Video Monitor
        self.monitor_youtube_videos.cancel()

    @tasks.loop(time=datetime.time(hour=17, minute=0, second=0, tzinfo=config.TIMEZONE))
    async def clean_channel_members_task(self) -> None:
        if datetime.datetime.now(tz=config.TIMEZONE).weekday() == calendar.SUNDAY:
            kick_list = await self._get_channel_members_to_kick()
            for member in kick_list:
                # Sleep to safely avoid rate limiting (50 requests per second)
                await asyncio.sleep(0.2)

                try:
                    await member.send(
                        "You have been removed from the Jim's Garage server "
                        "because you joined over a week ago and haven't "
                        "accepted the rules. If you believe this was a "
                        "mistake, please feel free to rejoin the server and "
                        "reach out to a mod."
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
                    member.joined_at.strftime("%Y-%m-%d %H:%M")
                    if member.joined_at
                    else "Unknown",
                    member.roles,
                )

            logger.info("Cleaned %s members.", len(kick_list))
            await self.bot.log_bot_event(
                event="Task - 🧹 Member Cleanup",
                details=f"Cleaned {len(kick_list)} members.",
            )

    @tasks.loop(minutes=5)
    async def clean_channel_members_task_dry_run(self) -> None:
        # DRY_RUN mode: Log what would have happened but take no action
        kick_list = await self._get_channel_members_to_kick()
        for member in kick_list:
            # Sleep to safely avoid rate limiting (50 requests per second)
            await asyncio.sleep(0.2)

            logger.info(
                "DRY_RUN: Would have sent DM to %s (%s) before kicking",
                member.display_name,
                member,
            )
            logger.info(
                "DRY_RUN: Would have kicked %s (%s) from the server - "
                "joined %s - roles: %s",
                member.display_name,
                member,
                member.joined_at.strftime("%Y-%m-%d %H:%M")
                if member.joined_at
                else "Unknown",
                member.roles,
            )

        logger.info("DRY_RUN: Would have cleaned %s members.", len(kick_list))
        await self.bot.log_bot_event(
            event="Task - 🧹 Member Cleanup (DRY_RUN)",
            details=f"Would have cleaned {len(kick_list)} members.",
        )

    async def _get_channel_members_to_kick(self) -> set[discord.Member]:
        """
        Get the list of members that joined over 1 week ago and do not have the
        Garage Member role (meaning they have not accepted the rules).
        """
        if not (guild := self.bot.get_guild(config.GUILDS.JIMS_GARAGE)):
            msg = f"Guild with ID {config.GUILDS.JIMS_GARAGE} not found"
            raise ValueError(msg)
        logger.info("Cleaning channel members for %s (%s)", guild.name, guild.id)
        await self.bot.log_bot_event(
            event=f"Task - 🧹 Member Cleanup{' (DRY_RUN)' if config.DRY_RUN else ''}"
        )

        kick_list = set()

        for member in guild.members:
            if not (joined_time := member.joined_at):
                logger.warning("Member %s has no `joined_at` timestamp", member)
                continue
            if (
                not any(role.id == config.ROLES.BOTS for role in member.roles)
                and not any(
                    role.id == config.ROLES.GARAGE_MEMBER for role in member.roles
                )
                and (datetime.datetime.now(tz=config.TIMEZONE) - joined_time)
                > datetime.timedelta(weeks=1)
            ):
                kick_list.add(member)

        return kick_list

    @clean_channel_members_task.before_loop
    @clean_channel_members_task_dry_run.before_loop
    async def before_clean_channel_members(self) -> None:
        """Called before the task loop starts"""
        logger.info("clean_channel_members task is starting up...")
        await self.bot.wait_until_ready()  # Wait for bot to be ready before starting

    @tasks.loop(minutes=5)
    async def monitor_youtube_videos(self) -> None:
        """Monitor YouTube videos for new uploads"""
        for feed_name, feed_parser in self.youtube_feeds.items():
            logger.debug("Checking %s for new videos", feed_name)
            if new_videos := feed_parser.get_new_videos():
                logger.info("New videos found for %s: %s", feed_name, new_videos)
                await self.bot.log_bot_event(
                    event="Task - YouTube Video Monitor",
                    details=f"New videos found for {feed_name}: {new_videos}",
                )
            else:
                logger.debug("No new videos found")
                continue

            # If new videos found, post to the #bot-playground channel if config.DRY_RUN
            # else post to #announcements channel
            if config.DRY_RUN_YOUTUBE:
                channel = self.bot.get_channel(config.CHANNELS.BOT_PLAYGROUND)
            else:
                channel = self.bot.get_channel(config.CHANNELS.ANNOUNCEMENTS)

            if channel and isinstance(channel, discord.TextChannel):
                for video in new_videos:
                    if not video or not isinstance(video, FeedParserDict):
                        logger.warning("Invalid YouTube video found: %s", video)
                        continue
                    embed = discord.Embed(
                        title=f"New video posted to {video.get('author', 'Unknown')}",
                        description=(
                            f"**[{getattr(video, 'title', 'No title found')}]"
                            f"({getattr(video, 'link', 'No link found')})**"
                        ),
                        color=discord.Color.purple(),
                    )
                    embed.add_field(
                        name="Summary",
                        value=getattr(video, "summary", "No summary found").split("\n")[
                            0
                        ],
                        inline=False,
                    )
                    embed.set_image(url=feed_parser.get_thumbnail_from_entry(video))
                    logger.info(
                        "Sending embed log message to %s: %s",
                        channel.name,
                        embed.to_dict(),
                    )

                    await channel.send(embed=embed)
            else:
                logger.warning(
                    "Could not find channel with ID %s or it is not a TextChannel",
                    config.CHANNELS.BOT_PLAYGROUND
                    if config.DRY_RUN
                    else config.CHANNELS.ANNOUNCEMENTS,
                )

    @monitor_youtube_videos.before_loop
    async def before_monitor_youtube_videos(self) -> None:
        """Called before the task loop starts"""
        logger.info("monitor_youtube_videos task is starting up...")
        for feed_name, feed_url in config.YOUTUBE_FEEDS.items():
            logger.info("Initializing YouTube feed parser for %s", feed_name)
            self.youtube_feeds[feed_name] = youtube.YoutubeFeedParser(
                feed_name.lower(), feed_url
            )
            logger.info("Initialized YouTube feed parser for %s", feed_name)
        logger.info("Initialized %d YouTube video monitors", len(self.youtube_feeds))
        await self.bot.wait_until_ready()

        if config.DRY_RUN_YOUTUBE:
            channel = self.bot.get_channel(config.CHANNELS.BOT_PLAYGROUND)
            if not isinstance(channel, discord.TextChannel):
                logger.error(
                    "Invalid channel specified in DRY_RUN_YOUTUBE mode: %s", channel
                )
                return

            for feed_name, feed in self.youtube_feeds.items():
                logger.debug(
                    "DRY_RUN_YOUTUBE mode: posting most recent video for %s",
                    feed_name.title(),
                )
                latest_video = feed.get_latest_video()
                logger.debug("Latest video: %s", latest_video)
                embed = discord.Embed(
                    title=f"(DRY_RUN) Most recent video found for "
                    f"{getattr(latest_video, 'author', 'Unknown')}",
                    description=(
                        f"**[{getattr(latest_video, 'title', 'No title found')}]"
                        f"({getattr(latest_video, 'link', 'No link found')})**"
                    ),
                    color=discord.Color.purple(),
                )
                embed.add_field(
                    name="Summary",
                    value=getattr(latest_video, "summary", "No summary found").split(
                        "\n"
                    )[0],
                    inline=False,
                )
                embed.set_image(url=feed.get_thumbnail_from_entry(latest_video))
                logger.info(
                    "Sending embed log message to %s: %s", channel.name, embed.to_dict()
                )
                await channel.send(embed=embed)
