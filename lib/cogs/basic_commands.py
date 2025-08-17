import logging
import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
    from lib.bot import DiscordBot  # noqa: F401 RUF100 - used in type annotations

logger: logging.Logger = logging.getLogger(__name__)

QUALITY_EMOJIS = {
    "excellent": "🟢",
    "good": "🟡",
    "fair": "🟠",
    "poor": "🔴",
}
WS_LATENCY_THRESHOLD = {
    "excellent": 100,
    "good": 200,
    "fair": 500,
}
API_LATENCY_THRESHOLD = {
    "excellent": 150,
    "good": 300,
    "fair": 600,
}


class BasicCommands(commands.Cog):
    def __init__(self, bot: "DiscordBot") -> None:
        self.bot = bot

    @commands.command()
    async def hello(self, ctx: commands.Context) -> None:
        """Responds with Hello"""
        logger.info("Received 'hello' from %s", ctx.author)
        await ctx.send("Hello")

    @commands.command()
    async def ping(self, ctx: commands.Context) -> None:
        """Responds with Pong"""
        logger.info("Received 'ping' from %s", ctx.author)
        await ctx.send("Pong")

    @discord.app_commands.command(  # pyre-ignore[56]
        name="hello", description="Responds with Hello world."
    )
    async def slash_hello(self, interaction: discord.Interaction) -> None:
        """Responds with 'Hello world.'"""
        logger.info("Received slash 'hello' from %s", interaction.user)
        await interaction.response.send_message("Hello world.")  # type: ignore[attr-defined]

    @discord.app_commands.command(  # pyre-ignore[56]
        name="ping",
        description="""
        Test the bot's Websocket latency and API response time.
        """,
    )
    async def slash_ping(self, interaction: discord.Interaction) -> None:
        """
        Respond with the bot's latency information.
        - Websocket latency: the heartbeat latency between the bot and Discord.
        - API response time: the time to send and receive a response from Discord's API.
        - Uptime: the time since the bot started running.
        """
        logger.info("Received slash 'ping' from %s", interaction.user)

        # Create the embed with ping information
        embed = discord.Embed(
            title="🏓 Pong!",
            description="Bot latency and response time information",
            color=discord.Color.green(),
        )

        # WebSocket latency (heartbeat latency)
        ws_latency = self.bot.latency * 1000  # Convert to milliseconds

        # Determine latency quality
        if ws_latency < WS_LATENCY_THRESHOLD["excellent"]:
            ws_status = "Excellent"
        elif ws_latency < WS_LATENCY_THRESHOLD["good"]:
            ws_status = "Good"
        elif ws_latency < WS_LATENCY_THRESHOLD["fair"]:
            ws_status = "Fair"
        else:
            ws_status = "Poor"

        embed.add_field(
            name=f"{QUALITY_EMOJIS[ws_status.lower()]} WebSocket Latency",
            value=f"{ws_latency:.1f}ms\n*({ws_status})*",
            inline=True,
        )

        # Record start time for API response measurement
        start_time = time.perf_counter()

        # Send initial response to measure API response time
        await interaction.response.send_message(embed=embed)  # type: ignore[attr-defined]

        # Calculate API response time
        end_time = time.perf_counter()
        api_latency = (end_time - start_time) * 1000  # Convert to milliseconds

        # Determine API latency quality
        if api_latency < API_LATENCY_THRESHOLD["excellent"]:
            api_status = "Excellent"
        elif api_latency < API_LATENCY_THRESHOLD["good"]:
            api_status = "Good"
        elif api_latency < API_LATENCY_THRESHOLD["fair"]:
            api_status = "Fair"
        else:
            api_status = "Poor"

        # Update the embed with API response time
        embed.add_field(
            name=f"{QUALITY_EMOJIS[api_status.lower()]} API Response Time",
            value=f"{api_latency:.1f}ms\n*({api_status})*",
            inline=True,
        )

        # Add bot uptime information
        if hasattr(self.bot, "startup_time"):
            uptime = time.time() - self.bot.startup_time
            hours, remainder = divmod(int(uptime), 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{hours}h {minutes}m {seconds}s"
        else:
            uptime_str = "Unknown"

        embed.add_field(name="⏱️ Uptime", value=uptime_str, inline=True)

        # Add footer with timestamp
        embed.set_footer(
            text=f"Requested by {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url,
        )
        embed.timestamp = interaction.created_at

        # Edit the original response with the updated embed
        try:
            await interaction.edit_original_response(embed=embed)
        except discord.NotFound:
            # Fallback if editing fails
            logger.warning("Could not edit original ping response")
