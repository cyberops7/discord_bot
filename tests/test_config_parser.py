"""Unit tests for config_parser.py"""

import pytest
from pytest_mock import MockerFixture

from lib.config_parser import (
    eval_ast,
    resolve_env_token,
    resolve_format_token,
    resolve_math_token,
    resolve_nested_dict,
    resolve_value,
    resolve_values,
)


@pytest.mark.parametrize(
    ("expr", "result"),
    [
        ("1 + 2 * (3 - 4)", -1),
        ("1 + 2 * (3 - 4) / 5", 0.6),
        ("-3", -3),
        ("-3.14", -3.14),
    ],
)
def test_eval_ast_valid_expression(expr: str, result: float) -> None:
    assert eval_ast(expr) == result


@pytest.mark.parametrize(
    ("expr", "error_msg"),
    [
        ("1 << 2", "Unsupported binary operator"),
        ("not 3", "Unsupported unary operator"),
    ],
)
def test_eval_ast_invalid_operator(expr: str, error_msg: str) -> None:
    with pytest.raises(ValueError, match=error_msg):
        eval_ast(expr)


def test_eval_ast_invalid_expression_type() -> None:
    with pytest.raises(ValueError, match="Unsupported expression"):
        eval_ast("[1, 2, 3]")


def test_eval_ast_failure() -> None:
    with pytest.raises(ValueError, match="Failed to evaluate expression"):
        eval_ast("1 / 0")


def test_resolve_env_token(mocker: MockerFixture) -> None:
    token_str = "@env ENV_VAR,default_value"  # noqa: S105
    env_var_name = "ENV_VAR"
    expected_value = "env_var_value"

    mocker.patch(
        "os.getenv",
        side_effect=lambda call_param, default_value: expected_value
        if call_param == env_var_name
        else default_value,
    )
    resolved_value = resolve_env_token(token_str)

    assert resolved_value == expected_value


def test_resolve_env_token_no_default(mocker: MockerFixture) -> None:
    token_str = "@env ENV_VAR"  # noqa: S105
    env_var_name = "ENV_VAR"
    expected_value = None

    mocker.patch(
        "os.getenv",
        side_effect=lambda call_param, default_value: expected_value
        if call_param == env_var_name
        else default_value,
    )
    resolved_value = resolve_env_token(token_str)

    assert resolved_value == expected_value


def test_resolve_env_token_no_keyword() -> None:
    token_str = "@ev ENV_VAR,default_value"  # noqa: S105
    with pytest.raises(
        ValueError,
        match=f"'@env' not found in token: {token_str}",
    ):
        resolve_env_token(token_str)


def test_resolve_env_token_bad_env_name(mocker: MockerFixture) -> None:
    token_str = "@env ENV_VAR,default_value"  # noqa: S105
    env_var_name = "ENV_VAR"
    default_value = "default_value"

    mocker.patch(
        "os.getenv",
        side_effect=lambda call_param, default: default_value
        if call_param == env_var_name
        else default,
    )
    resolved_value = resolve_env_token(token_str)
    assert resolved_value == default_value


def test_resolve_env_token_bad_token() -> None:
    with pytest.raises(
        ValueError, match="Environment variable name missing in @env token"
    ):
        resolve_env_token("@env")


def test_resolve_format_token_single(mocker: MockerFixture) -> None:
    token_str = "@format Hello: {@env ENV_VAR1,default_value1}"  # noqa: S105
    sub_token_value = "Jim"  # noqa: S105
    expected_str = f"Hello: {sub_token_value}"

    mocker.patch(
        "lib.config_parser.resolve_value",
        return_value=sub_token_value,
    )
    resolved_str = resolve_format_token(token_str)

    assert resolved_str == expected_str


def test_resolve_format_token_multiple(mocker: MockerFixture) -> None:
    token_str = (
        "@format Hello: {@env ENV_VAR1,default_value1}'s {@env ENV_VAR2,default_value2}"  # noqa: S105
    )
    sub_token_value1 = "Jim"  # noqa: S105
    sub_token_value2 = "Garage"  # noqa: S105
    expected_str = f"Hello: {sub_token_value1}'s {sub_token_value2}"

    mocker.patch(
        "lib.config_parser.resolve_value",
        side_effect=[sub_token_value1, sub_token_value2],
    )
    resolved_str = resolve_format_token(token_str)

    assert resolved_str == expected_str


def test_resolve_format_token_resolved_to_none(mocker: MockerFixture) -> None:
    token_str = "@format Hello: {@env ENV_VAR1}"  # noqa: S105
    sub_token_value = None
    expected_str = "Hello: "

    mocker.patch(
        "lib.config_parser.resolve_value",
        return_value=sub_token_value,
    )
    resolved_str = resolve_format_token(token_str)

    assert resolved_str == expected_str


def test_resolve_format_token_invalid_token_keyword() -> None:
    token_str = "@form Hello world"  # noqa: S105
    with pytest.raises(
        ValueError,
        match=f"Invalid @format token: {token_str}. "
        f"Error: '@format' not found in token: {token_str}",
    ):
        resolve_format_token(token_str)


def test_resolve_format_token_invalid_token_no_nested() -> None:
    token_str = "@format Hello world"  # noqa: S105
    with pytest.raises(
        ValueError,
        match=f"Invalid @format token: {token_str}. "
        f"Error: No tokens found in @format token",
    ):
        resolve_format_token(token_str)


def test_resolve_math_token() -> None:
    assert resolve_math_token("@math 10 + 2 * 3") == 16


def test_resolve_math_token_no_keyword() -> None:
    token_str = "@mat 10 + 2 * 3"  # noqa: S105
    with pytest.raises(ValueError, match="'@math' not found in token:"):
        resolve_math_token(token_str)


def test_resolve_math_token_invalid() -> None:
    token_str = "@math 10 a 3"  # noqa: S105
    with pytest.raises(ValueError, match=f"Invalid @math expression: {token_str}."):
        resolve_math_token(token_str)


def test_resolve_value_simple_str() -> None:
    assert resolve_value("just_a_string") == "just_a_string"


@pytest.mark.parametrize("val", [123, 123.456, True, False])
def test_resolve_value_non_str(val: float | bool) -> None:
    assert resolve_value(val) == val  # pyre-ignore[6]


def test_resolve_value_env_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV_VAR", "env_value")
    assert resolve_value("@env ENV_VAR,default_value") == "env_value"


def test_resolve_value_format_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV_VAR", "universe")
    assert (
        resolve_value("@format The answer to the {@env ENV_VAR}: {@math 21 * 2}")
        == "The answer to the universe: 42"
    )


@pytest.mark.parametrize(
    ("expr", "result"),
    [
        ("1 + 2 * (3 - 4)", -1),
        ("1 + 2 * (3 - 4) / 5", 0.6),
        ("-10", -10),
    ],
)
def test_resolve_value_math_token(expr: str, result: float) -> None:
    assert resolve_value(f"@math {expr}") == result


def test_resolve_nested_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_ENV_VAR", "Jim")
    data = {
        "plain_str": "plain_value",
        "env_var": "@env TEST_ENV_VAR",
        "math": "@math 3 * 6",
        "format": "@format Hello: {@env TEST_ENV_VAR} - {@math 10 + 2 * 3}",
        "nest": {"math": "@math 4 + 2"},
    }

    assert resolve_nested_dict(data) == {
        "plain_str": "plain_value",
        "env_var": "Jim",
        "math": 18,
        "format": "Hello: Jim - 16",
        "nest": {
            "math": 6,
        },
    }


def test_resolve_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration test"""
    monkeypatch.setenv("TEST_ENV_VAR", "Jim")
    data = {
        "plain_str": "plain_value",
        "env_var": "@env TEST_ENV_VAR",
        "math": "@math 3 * 6",
        "format": "@format Hello: {@env TEST_ENV_VAR} - {@math 10 + 2 * 3}",
        "nest": {"math": "@math 4 + 2"},
    }

    assert resolve_values(data) == {
        "plain_str": "plain_value",
        "env_var": "Jim",
        "math": 18,
        "format": "Hello: Jim - 16",
        "nest": {
            "math": 6,
        },
    }
