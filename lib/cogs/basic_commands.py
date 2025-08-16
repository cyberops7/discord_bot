import logging
from typing import TYPE_CHECKING

from discord.ext import commands

if TYPE_CHECKING:
    from lib.bot import DiscordBot  # noqa: F401 RUF100 - used in type annotations

logger: logging.Logger = logging.getLogger(__name__)


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
