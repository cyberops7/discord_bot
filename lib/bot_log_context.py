"""LogContext class"""

import logging
from dataclasses import dataclass, field

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
            if config.LOG_CHANNEL:
                self.log_channel = config.LOG_CHANNEL
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
