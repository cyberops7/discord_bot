"""Configuration module for loading and accessing app constants"""

import datetime
import logging
import tomllib
from datetime import tzinfo
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import yaml

# change this to DEBUG if debugging config initialization
logger: logging.Logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ConfigDict:
    """A dictionary-like object that allows attribute access to nested values"""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        # Convert nested dictionaries to ConfigDict objects
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, ConfigDict(value))
            else:
                setattr(self, key, value)

    def __contains__(self, key: str) -> bool:
        """Support 'in' operator"""
        return key in self._data

    def __delattr__(self, name: str) -> None:
        """Support 'del' operator"""
        if name in self._data:
            del self._data[name]
            super().__delattr__(name)
        else:
            msg = f"Attribute '{name}' does not exist and cannot be deleted"
            raise AttributeError(msg)

    def __getattr__(self, name: str) -> Any:
        """Allow accessing config values as attributes"""
        if name in self._data:
            return self._data[name]
        msg = f"Configuration key '{name}' not found"
        raise AttributeError(msg)

    def __getitem__(self, key: str) -> Any:
        """Allow dictionary-style access if needed"""
        return self._data[key]

    def __repr__(self) -> str:
        """Better representation for debugging"""
        return f"ConfigDict({self._data})"

    def get(self, key: str, default: object | None = None) -> Any:
        """Get configuration value with optional default"""
        return self._data.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        """Return the underlying dictionary"""
        return self._data.copy()


class Config:
    """Configuration class to hold all app constants"""

    _instance: Optional["Config"] = None
    _config_data: ConfigDict | None = None
    _config_path: Path | None = None
    _pyproject_path: Path | None = None

    def __getattr__(self, name: str) -> Any:
        """Allow accessing config values as attributes"""
        return getattr(self._config_data, name)

    def __new__(cls) -> Optional["Config"]:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._load_config()
        return cls._instance

    @classmethod
    def set_config_paths(
        cls, config_path: Path | None = None, pyproject_path: Path | None = None
    ) -> None:
        """Override the default config and pyproject paths for testing"""
        cls._config_path = config_path
        cls._pyproject_path = pyproject_path

    @classmethod
    def _load_config(cls) -> None:
        """Load configuration from a YAML file"""
        if cls._config_path is None:
            config_path = Path(__file__).parent.parent / "conf/config.yaml"
        else:
            config_path = cls._config_path

        try:
            with Path.open(config_path) as file:
                raw_data = yaml.safe_load(file)
        except FileNotFoundError:
            msg = f"Configuration file not found: {config_path}"
            raise FileNotFoundError(msg) from None
        except yaml.YAMLError as e:
            msg = f"Error parsing YAML configuration: {e}"
            raise ValueError(msg) from e

        # Load version from pyproject.toml
        version = cls._load_version_from_pyproject()
        raw_data["VERSION"] = version

        # Convert a timezone string to a timezone object and replace it
        tz_string = raw_data.get("TIMEZONE", "UTC")
        raw_data["TIMEZONE"] = cls._parse_timezone(tz_string)

        cls._config_data = ConfigDict(raw_data)

    @classmethod
    def _load_version_from_pyproject(cls) -> str:
        """Load version from the pyproject.toml file"""
        if cls._pyproject_path is None:
            pyproject_path = Path(__file__).parent.parent / "pyproject.toml"
        else:
            pyproject_path = cls._pyproject_path

        try:
            with Path.open(pyproject_path, "rb") as file:
                pyproject_data = tomllib.load(file)
                version = pyproject_data.get("project", {}).get("version")

                if not version:
                    msg = "Version not found in pyproject.toml"
                    raise ValueError(msg)

                return version

        except FileNotFoundError:
            msg = f"pyproject.toml not found: {pyproject_path}"
            raise FileNotFoundError(msg) from None

    @classmethod
    def _parse_timezone(cls, tz_string: str) -> tzinfo:
        """Parse timezone string to timezone object"""
        try:
            return ZoneInfo(tz_string)
        except KeyError as e:
            logger.warning("Invalid timezone '%s': %s", tz_string, e)
        except ValueError as e:
            logger.warning("Could not parse timezone '%s': %s", tz_string, e)
        except TypeError as e:
            logger.warning("Invalid type provided for timezone '%s': %s", tz_string, e)

            # Fallback to UTC in case of failure
        logger.warning("Falling back to UTC")
        return datetime.UTC

    def get(self, key: str, default: object | None = None) -> Any:
        """Get configuration value with optional default"""
        if self._config_data:
            return self._config_data.get(key, default)
        return None


# Create a singleton instance
config = Config()
