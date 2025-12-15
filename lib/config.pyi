from collections.abc import ItemsView, KeysView, ValuesView
from datetime import tzinfo
from os import PathLike
from typing import Any, Self

import discord

class ConfigDict:
    def __init__(self, data: dict[str, Any]) -> None: ...
    def __contains__(self, key: str) -> bool: ...
    def __delattr__(self, name: str) -> None: ...
    def __getattr__(self, name: str) -> Any: ...  # noqa: ANN401 - Dynamic dict-like access
    def __getitem__(self, key: str) -> Any: ...  # noqa: ANN401 - Dynamic dict-like access
    def get(self, key: str, default: object | None = None) -> Any: ...  # noqa: ANN401 - Dynamic dict-like access
    def items(self) -> ItemsView[str, Any]: ...
    def keys(self) -> KeysView[str]: ...
    def to_dict(self) -> dict[str, Any]: ...
    def values(self) -> ValuesView[Any]: ...

class _Channels(ConfigDict):
    ANNOUNCEMENTS: int
    BOT_LOGS: int
    BOT_PLAYGROUND: int
    MOUSETRAP: int
    RULES: int

class _Guilds(ConfigDict):
    JIMS_GARAGE: int

class _Roles(ConfigDict):
    ADMIN: int
    BOTS: int
    GARAGE_MEMBER: int
    JIMS_GARAGE: int
    MOD: int
    VIP: int

class _YoutubeFeed(ConfigDict):
    JIMS_GARAGE: str
    TECH_BENCH: str

class Config:
    _instance: Config | None
    _config_data: ConfigDict | None
    _config_path: str | PathLike[str] | None
    _pyproject_path: str | PathLike[str] | None

    API_PORT: int
    BOT_TOKEN: str | None
    CHANNELS: _Channels
    DRY_RUN: bool
    DRY_RUN_YOUTUBE: bool
    GUILDS: _Guilds
    LOG_CHANNEL: discord.TextChannel | None
    LOG_DIR: str
    LOG_FILE: str
    LOG_LEVEL_FILE: str
    LOG_LEVEL_STDOUT: str
    ROLES: _Roles
    TIMEZONE: tzinfo
    VERSION: str
    YOUTUBE_FEEDS: _YoutubeFeed

    def __new__(cls) -> Self: ...
    def __getattr__(self, name: str) -> Any: ...  # noqa: ANN401 - Dynamic config access
    def get(self, key: str, default: object | None = None) -> Any: ...  # noqa: ANN401 - Dynamic config access
    @classmethod
    def set_config_paths(
        cls,
        config_path: str | PathLike[str] | None = None,
        pyproject_path: str | PathLike[str] | None = None,
    ) -> None: ...
    @classmethod
    def _override_with_env_vars(
        cls, data: dict[str, Any], prefix: str = ""
    ) -> dict[str, Any]: ...
    @classmethod
    def _convert_env_value(
        cls,
        env_value: str,
        original_value: Any,  # noqa: ANN401
    ) -> Any: ...  # noqa: ANN401
    @classmethod
    def _load_config(cls) -> None: ...
    @classmethod
    def _load_version_from_pyproject(cls) -> str: ...
    @classmethod
    def _parse_timezone(cls, tz_string: str) -> tzinfo: ...

config: Config
