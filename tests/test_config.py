"""Tests for configuration module"""

import datetime
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pytest
import yaml
from pytest_mock import MockerFixture

from lib.config import Config, ConfigDict


class TestConfigDict:
    """Tests for ConfigDict class"""

    def test_init_with_simple_data(self) -> None:
        """Test ConfigDict initialization with simple data"""
        data = {"key1": "value1", "key2": 42}
        config_dict = ConfigDict(data)

        assert config_dict._data == data
        assert config_dict.key1 == "value1"
        assert config_dict.key2 == 42

    def test_init_with_nested_data(self) -> None:
        """Test ConfigDict initialization with nested dictionaries"""
        data = {
            "top_level": "value",
            "nested": {
                "inner_key": "inner_value",
                "deep_nested": {"deep_key": "deep_value"},
            },
        }
        config_dict = ConfigDict(data)

        assert config_dict.top_level == "value"
        assert isinstance(config_dict.nested, ConfigDict)
        assert config_dict.nested.inner_key == "inner_value"
        assert isinstance(config_dict.nested.deep_nested, ConfigDict)
        assert config_dict.nested.deep_nested.deep_key == "deep_value"

    def test_contains_operator(self) -> None:
        """Test __contains__ operator"""
        data = {"existing_key": "value"}
        config_dict = ConfigDict(data)

        assert "existing_key" in config_dict
        assert "nonexistent_key" not in config_dict

    def test_getattr_existing_key(self) -> None:
        """Test __getattr__ with an existing key"""
        data = {"existing_key": "existing_value"}
        config_dict = ConfigDict(data)

        # Add a key to _data without setting it as an attribute
        config_dict._data["test_key"] = "test_value"

        assert config_dict.test_key == "test_value"

    def test_getattr_nonexistent_key(self) -> None:
        """Test __getattr__ with a nonexistent key raises AttributeError"""
        data = {"existing_key": "value"}
        config_dict = ConfigDict(data)

        with pytest.raises(
            AttributeError, match="Configuration key 'nonexistent' not found"
        ):
            _ = config_dict.nonexistent

    def test_delattr_existing_key(self) -> None:
        """Test __delattr__ with an existing key"""
        data = {"test_key": "test_value"}
        config_dict = ConfigDict(data)

        # Verify the key exists
        assert hasattr(config_dict, "test_key")

        # Delete the attribute
        del config_dict.test_key

        # Verify it's gone from both the attribute and the internal dict
        assert not hasattr(config_dict, "test_key")
        assert "test_key" not in config_dict._data

    def test_delattr_nonexistent_key(self) -> None:
        """Test __delattr__ with a nonexistent key raises AttributeError"""
        data = {"existing_key": "value"}
        config_dict = ConfigDict(data)

        with pytest.raises(
            AttributeError,
            match="Attribute 'nonexistent' does not exist and cannot be deleted",
        ):
            del config_dict.nonexistent

    def test_getitem_existing_key(self) -> None:
        """Test __getitem__ with an existing key"""
        data = {"test_key": "test_value"}
        config_dict = ConfigDict(data)

        assert config_dict["test_key"] == "test_value"

    def test_getitem_nonexistent_key(self) -> None:
        """Test __getitem__ with a nonexistent key raises KeyError"""
        data = {"existing_key": "value"}
        config_dict = ConfigDict(data)

        with pytest.raises(KeyError):
            _ = config_dict["nonexistent"]

    def test_repr(self) -> None:
        """Test __repr__ method"""
        data = {"key": "value"}
        config_dict = ConfigDict(data)

        expected = f"ConfigDict({data})"
        assert repr(config_dict) == expected

    def test_get_existing_key(self) -> None:
        """Test get method with an existing key"""
        data = {"test_key": "test_value"}
        config_dict = ConfigDict(data)

        assert config_dict.get("test_key") == "test_value"

    def test_get_nonexistent_key_with_default(self) -> None:
        """Test get method with a nonexistent key and default value"""
        data = {"existing_key": "value"}
        config_dict = ConfigDict(data)

        assert config_dict.get("nonexistent", "default") == "default"

    def test_get_nonexistent_key_no_default(self) -> None:
        """Test get method with a nonexistent key and no default"""
        data = {"existing_key": "value"}
        config_dict = ConfigDict(data)

        assert config_dict.get("nonexistent") is None

    def test_to_dict(self) -> None:
        """Test to_dict method returns a copy of data"""
        data = {"key1": "value1", "key2": 42}
        config_dict = ConfigDict(data)

        result = config_dict.to_dict()
        assert result == data
        assert result is not config_dict._data  # Should be a copy


class TestConfig:
    """Tests for Config class"""

    @pytest.fixture(autouse=True)
    def setup_method(self) -> None:
        """Reset Config singleton before each test"""
        Config._instance = None
        Config._config_data = None

    @pytest.fixture
    def mock_logger(self, mocker: MockerFixture) -> Mock:
        """Fixture to mock the logger"""
        return mocker.patch("lib.config.logger")

    def test_singleton_behavior(self) -> None:
        """Test that Config follows a singleton pattern"""
        with patch.object(Config, "_load_config"):
            config1 = Config()
            config2 = Config()

            assert config1 is config2

    def test_load_config_success(self, mocker: MockerFixture) -> None:
        """Test successful configuration loading"""
        test_config = {"CHANNELS": {"BOT_LOGS": 123456789, "BOT_PLAYGROUND": 987654321}}
        mock_yaml_content = yaml.dump(test_config)
        mock_file = mocker.mock_open(read_data=mock_yaml_content)
        mock_path_instance = mocker.MagicMock()
        mock_path_instance.__truediv__.return_value = mock_path_instance
        mock_path_instance.parent.parent = mock_path_instance
        mock_path_open = mocker.patch("pathlib.Path.open", mock_file)
        mocker.patch("pathlib.Path", return_value=mock_path_instance)
        mocker.patch.object(
            Config, "_load_version_from_pyproject", return_value="1.0.0"
        )

        Config._load_config()

        assert isinstance(Config._config_data, ConfigDict)
        mock_path_open.assert_called_once()

        # Ensure _config_data is not None before accessing its attributes
        assert Config._config_data is not None
        # Store in a variable with an explicit type to help Pyre know it's not None
        config_data: ConfigDict = Config._config_data
        assert test_config["CHANNELS"]["BOT_LOGS"] == config_data.CHANNELS.BOT_LOGS
        assert config_data.VERSION == "1.0.0"

    def test_load_config_file_not_found(self, mocker: MockerFixture) -> None:
        """Test FileNotFoundError when a config file does not exist"""
        mock_path_instance = mocker.MagicMock()
        mock_path_instance.__truediv__.return_value = mock_path_instance
        mock_path_instance.parent.parent = mock_path_instance
        mock_path_open = mocker.patch(
            "pathlib.Path.open", side_effect=FileNotFoundError
        )
        mocker.patch("pathlib.Path", return_value=mock_path_instance)

        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            Config._load_config()

        mock_path_open.assert_called_once()

    def test_load_config_yaml_error(self, mocker: MockerFixture) -> None:
        """Test ValueError when YAML parsing fails"""
        invalid_yaml = "invalid: yaml: content: ["

        mock_path_instance = mocker.MagicMock()
        mock_path_instance.__truediv__.return_value = mock_path_instance
        mock_path_instance.parent.parent = mock_path_instance
        mock_file = mocker.mock_open(read_data=invalid_yaml)
        mock_path_open = mocker.patch("pathlib.Path.open", mock_file)
        mocker.patch("pathlib.Path", return_value=mock_path_instance)

        with pytest.raises(ValueError, match="Error parsing YAML configuration"):
            Config._load_config()

        mock_path_open.assert_called_once()

    def test_load_version_from_pyproject_success(self, mocker: MockerFixture) -> None:
        """Test successful 'version' loading from pyproject.toml"""
        mock_toml_data = {"project": {"version": "2.1.0", "name": "test-project"}}

        with (
            patch("builtins.open", mocker.mock_open(read_data=b"mock_toml_content")),
            patch("lib.config.tomllib.load", return_value=mock_toml_data),
        ):
            version = Config._load_version_from_pyproject()
            assert version == "2.1.0"

    def test_load_version_from_pyproject_file_not_found(
        self, mocker: MockerFixture
    ) -> None:
        """Test FileNotFoundError when pyproject.toml does not exist"""
        mock_path_instance = mocker.MagicMock()
        mock_path_instance.__truediv__.return_value = mock_path_instance
        mock_path_instance.parent.parent = mock_path_instance
        mock_path_open = mocker.patch(
            "pathlib.Path.open", side_effect=FileNotFoundError
        )
        mocker.patch("pathlib.Path", return_value=mock_path_instance)

        with pytest.raises(FileNotFoundError, match="pyproject.toml not found"):
            Config._load_version_from_pyproject()

        mock_path_open.assert_called_once()

    def test_load_version_from_pyproject_no_version_key(
        self, mocker: MockerFixture
    ) -> None:
        """Test ValueError when 'version' is not found in pyproject.toml"""
        mock_toml_data = {"project": {"name": "test-project"}}

        with (
            patch("builtins.open", mocker.mock_open(read_data=b"mock_toml_content")),
            patch("lib.config.tomllib.load", return_value=mock_toml_data),
            pytest.raises(ValueError, match="Version not found in pyproject.toml"),
        ):
            Config._load_version_from_pyproject()

    def test_load_version_from_pyproject_no_project_section(
        self, mocker: MockerFixture
    ) -> None:
        """Test ValueError when the project section is missing"""
        mock_toml_data = {"build-system": {"requires": ["setuptools"]}}

        with (
            patch("builtins.open", mocker.mock_open(read_data=b"mock_toml_content")),
            patch("lib.config.tomllib.load", return_value=mock_toml_data),
            pytest.raises(ValueError, match="Version not found in pyproject.toml"),
        ):
            Config._load_version_from_pyproject()

    def test_load_version_from_pyproject_empty_version(
        self, mocker: MockerFixture
    ) -> None:
        """Test ValueError when 'version' is an empty string"""
        # Mock TOML content with an empty 'version'
        mock_toml_data = {"project": {"version": "", "name": "test-project"}}

        with (
            patch("builtins.open", mocker.mock_open(read_data=b"mock_toml_content")),
            patch("lib.config.tomllib.load", return_value=mock_toml_data),
            pytest.raises(ValueError, match="Version not found in pyproject.toml"),
        ):
            Config._load_version_from_pyproject()

    def test_parse_timezone_success(self) -> None:
        """Test successful timezone parsing with a valid timezone string"""

        result = Config._parse_timezone("America/New_York")

        assert isinstance(result, ZoneInfo)
        assert str(result) == "America/New_York"

    def test_parse_timezone_utc(self) -> None:
        """Test parsing UTC timezone"""

        result = Config._parse_timezone("UTC")

        assert isinstance(result, ZoneInfo)
        assert str(result) == "UTC"

    @pytest.mark.parametrize(
        ("tz_string", "exception_type", "exception_value", "log_pattern"),
        [
            # KeyError scenario - invalid timezone name
            (
                "Invalid/Timezone",
                KeyError,
                "No time zone found with key Invalid/Timezone",
                "Invalid timezone '%s': %s",
            ),
            # ValueError scenario - empty string
            (
                "",
                ValueError,
                "ZoneInfo keys must be normalized relative paths, got: ",
                "Could not parse timezone '%s': %s",
            ),
            # TypeError scenario - None value
            (
                None,
                TypeError,
                "ZoneInfo keys must be strings, not NoneType",
                "Invalid type provided for timezone '%s': %s",
            ),
        ],
    )
    def test_parse_timezone_fallback_scenarios(
        self,
        mocker: MockerFixture,
        mock_logger: Mock,
        tz_string: str,
        exception_type: type[Exception],
        exception_value: str,
        log_pattern: str,
    ) -> None:
        """Test that various exceptions in _parse_timezone fall back to UTC"""
        mock_zoneinfo = mocker.patch("lib.config.ZoneInfo")
        mock_zoneinfo.side_effect = exception_type(exception_value)

        result = Config._parse_timezone(tz_string)

        assert result == datetime.UTC
        mock_logger.warning.assert_any_call(
            log_pattern, tz_string, mock_zoneinfo.side_effect
        )
        mock_logger.warning.assert_any_call("Falling back to UTC")

    def test_getattr_delegates_to_config_data(self) -> None:
        """Test that __getattr__ delegates to _config_data"""
        test_data = {"TEST_KEY": "test_value"}

        with patch.object(Config, "_load_config"):
            config_instance = Config()
            config_instance._config_data = ConfigDict(test_data)

            assert config_instance.TEST_KEY == "test_value"

    def test_getattr_with_nested_data(self) -> None:
        """Test __getattr__ with nested configuration data"""
        test_data = {"CHANNELS": {"BOT_LOGS": 123456789}}

        with patch.object(Config, "_load_config"):
            config_instance = Config()
            config_instance._config_data = ConfigDict(test_data)

            assert isinstance(config_instance.CHANNELS, ConfigDict)
            assert config_instance.CHANNELS.BOT_LOGS == 123456789

    def test_get_method_delegates_to_config_data(self) -> None:
        """Test that get method delegates to _config_data"""
        test_data = {"TEST_KEY": "test_value"}

        with patch.object(Config, "_load_config"):
            config_instance = Config()
            config_instance._config_data = ConfigDict(test_data)

            assert config_instance.get("TEST_KEY") == "test_value"
            assert config_instance.get("NONEXISTENT", "default") == "default"

    def test_get_method_returns_none_when_config_data_is_none(self) -> None:
        """Test that get method returns None when _config_data is None"""
        with patch.object(Config, "_load_config"):
            config_instance = Config()
            config_instance._config_data = None

            # Should return None regardless of key or default value
            assert config_instance.get("ANY_KEY") is None
            assert config_instance.get("ANY_KEY", "default") is None

    def test_full_integration_with_temp_file(self) -> None:
        """Test full integration with a temporary config file"""
        # Reset Config singleton before test
        Config._instance = None
        Config._config_data = None
        Config._config_path = None
        Config._pyproject_path = None

        test_data_dir = Path(__file__).parent / "data"
        config_file = test_data_dir / "config.yaml"
        toml_file = test_data_dir / "pyproject.toml"

        # Set the test file paths directly
        Config.set_config_paths(config_path=config_file, pyproject_path=toml_file)

        # Create a new Config instance which will load the test files
        config_instance = Config()

        # Test nested access
        assert config_instance.CHANNELS.BOT_LOGS == 11111
        assert config_instance.CHANNELS.BOT_PLAYGROUND == 22222
        assert config_instance.DATABASE.HOST == "localhost"
        assert config_instance.DATABASE.PORT == 5432
        assert config_instance.VERSION == "1.0.0"

        # Test `to_dict` functionality
        channels_dict = config_instance.CHANNELS.to_dict()
        with Path.open(config_file) as f:
            raw_config = yaml.safe_load(f)
            expected_channels = raw_config["CHANNELS"]
        assert channels_dict == expected_channels

        # Reset paths to ensure they don't affect other tests
        Config._instance = None
        Config._config_data = None
        Config._config_path = None
        Config._pyproject_path = None

    def test_default_paths_when_not_overridden(self, mocker: MockerFixture) -> None:
        """Test that default paths are used when not overridden"""
        # Reset Config singleton before test
        Config._instance = None
        Config._config_data = None
        Config._config_path = None
        Config._pyproject_path = None

        # Expected default paths
        expected_config_path = Path(__file__).parent.parent / "conf/config.yaml"
        expected_pyproject_path = Path(__file__).parent.parent / "pyproject.toml"

        path_open_spy = mocker.spy(Path, "open")

        # Mock yaml.safe_load to return a minimal valid config
        mock_yaml = mocker.patch(
            "yaml.safe_load", return_value={"TEST_KEY": "test_value"}
        )

        # Mock tomllib.load to return a minimal valid pyproject.toml
        mock_toml = mocker.patch(
            "lib.config.tomllib.load", return_value={"project": {"version": "1.0.0"}}
        )

        # Call _load_config directly to test path resolution
        Config._load_config()

        # Verify the Path constructor was called with the expected paths
        path_open_calls = [call[0][0] for call in path_open_spy.call_args_list]

        # Convert expected paths to absolute paths for comparison
        expected_config_path = expected_config_path.resolve()
        expected_pyproject_path = expected_pyproject_path.resolve()

        # Check if the expected paths were used
        # (allowing for paths to be absolute or relative)
        config_path_used = any(
            str(path) == str(expected_config_path)
            or path.name == expected_config_path.name
            for path in path_open_calls
        )

        pyproject_path_used = any(
            str(path) == str(expected_pyproject_path)
            or path.name == expected_pyproject_path.name
            for path in path_open_calls
        )

        # Assert that both expected paths were used
        assert config_path_used, (
            f"Expected config path {expected_config_path} not used. "
            f"Actual paths: {path_open_calls}"
        )
        assert pyproject_path_used, (
            f"Expected pyproject path {expected_pyproject_path} not used. "
            f"Actual paths: {path_open_calls}"
        )

        # Verify the YAML and TOML loaders were called
        assert mock_yaml.called, "yaml.safe_load was not called"
        assert mock_toml.called, "tomllib.load was not called"

        # Reset for other tests
        Config._instance = None
        Config._config_data = None
        Config._config_path = None
        Config._pyproject_path = None

    def test_config_data_type_annotation(self) -> None:
        """Test that _config_data maintains the correct type annotation"""
        with patch.object(Config, "_load_config"):
            _ = Config()

            # This tests the type annotation compliance
            assert Config._config_data is None or isinstance(
                Config._config_data, ConfigDict
            )


class TestConfigModule:
    """Tests for the module-level config instance"""

    @pytest.mark.no_mock_config  # type: ignore[misc]
    def test_module_config_instance_creation(self) -> None:
        """Test that a module-level config instance is created properly"""
        # Import the module config instance
        from lib.config import config  # noqa: PLC0415 imports at the top of the file

        assert isinstance(config, Config)

    def test_module_config_singleton_consistency(self) -> None:
        """Test that the module config instance follows a singleton pattern"""
        with patch.object(Config, "_load_config"):
            # Reset singleton state for this test
            original_instance = Config._instance
            Config._instance = None
            Config._config_data = None

            try:
                # Create two instances
                config1 = Config()
                config2 = Config()

                # Should be the same instance
                assert config1 is config2
            finally:
                # Restore original state
                Config._instance = original_instance


# Test fixtures for parametrized tests
@pytest.fixture
def sample_config_data() -> dict[str, Any]:
    """Fixture providing sample configuration data"""
    return {
        "CHANNELS": {
            "BOT_LOGS": 1390267799863165038,
            "BOT_PLAYGROUND": 1296529518793588748,
        },
        "SIMPLE_VALUE": "test_string",
        "NUMERIC_VALUE": 42,
    }


@pytest.fixture
def config_dict_instance(sample_config_data: dict[str, Any]) -> ConfigDict:
    """Fixture providing ConfigDict instance with sample data"""
    return ConfigDict(sample_config_data)


class TestConfigDictParametrized:
    """Parametrized tests for ConfigDict"""

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("SIMPLE_VALUE", "test_string"),
            ("NUMERIC_VALUE", 42),
        ],
    )
    def test_attribute_access_parametrized(
        self, config_dict_instance: ConfigDict, key: str, expected: str | int
    ) -> None:
        """Test attribute access with different data types"""
        assert getattr(config_dict_instance, key) == expected

    @pytest.mark.parametrize(
        ("key", "default", "expected"),
        [
            ("SIMPLE_VALUE", "default", "test_string"),
            ("NONEXISTENT", "default", "default"),
            ("NONEXISTENT", None, None),
        ],
    )
    def test_get_method_parametrized(
        self,
        config_dict_instance: ConfigDict,
        key: str,
        default: str | None,
        expected: str | None,
    ) -> None:
        """Test get method with different scenarios"""
        assert config_dict_instance.get(key, default) == expected
