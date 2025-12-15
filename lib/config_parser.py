"""
Parse a YAML config file and resolve special tokens to allow for dynamic configuration.
"""

import ast
import operator as op
import os
import re
from collections.abc import Callable
from typing import Any

BINARY_OPERATOR_TYPES = Callable[[int | float, int | float], int | float]
UNARY_OPERATOR_TYPES = Callable[[int | float], int | float]
ALLOWED_OPERATORS: dict[
    type[
        ast.Add
        | ast.Div
        | ast.Mod
        | ast.Mult
        | ast.Pow
        | ast.Sub
        | ast.USub
        | ast.operator
        | ast.unaryop
    ],
    BINARY_OPERATOR_TYPES | UNARY_OPERATOR_TYPES,
] = {
    ast.Add: op.add,  # Addition
    ast.Sub: op.sub,  # Subtraction
    ast.Mult: op.mul,  # Multiplication
    ast.Div: op.truediv,  # Division
    ast.Mod: op.mod,  # Modulus
    ast.Pow: op.pow,  # Exponentiation
    ast.USub: op.neg,  # Unary subtraction
}

# Separate dictionaries for binary and unary operators
ALLOWED_BINARY_OPERATORS: dict[
    type[ast.Add | ast.Div | ast.Mod | ast.Mult | ast.Pow | ast.Sub | ast.operator],
    BINARY_OPERATOR_TYPES,
] = {
    ast.Add: op.add,  # Addition
    ast.Sub: op.sub,  # Subtraction
    ast.Mult: op.mul,  # Multiplication
    ast.Div: op.truediv,  # Division
    ast.Mod: op.mod,  # Modulus
    ast.Pow: op.pow,  # Exponentiation
}

ALLOWED_UNARY_OPERATORS: dict[
    type[ast.USub | ast.unaryop | ast.operator], UNARY_OPERATOR_TYPES
] = {
    ast.USub: op.neg,  # Unary subtraction
}


def eval_ast(expr: str) -> int | float:
    """
    Safely evaluate an AST generated from a mathematical expression.
    Supports only basic mathematical operations.

    :param expr: The mathematical expression as a string.
    :return: The evaluated result (int or float).
    """

    def _eval(
        node: ast.Constant | ast.BinOp | ast.UnaryOp | ast.expr,
    ) -> int | float:
        if isinstance(node, ast.Constant):  # Numbers (e.g., 1, 2, 3)
            if not isinstance(node.value, int | float):
                msg = f"Expected numeric constant, got {type(node.value).__name__}"
                raise TypeError(msg)
            return node.value
        if isinstance(node, ast.BinOp):  # Binary operations (e.g., 2 + 3, 4 * 5)
            if type(node.op) not in ALLOWED_BINARY_OPERATORS:
                binary_msg = f"Unsupported binary operator: {type(node.op).__name__}"
                raise ValueError(binary_msg)
            return ALLOWED_BINARY_OPERATORS[type(node.op)](
                _eval(node.left), _eval(node.right)
            )
        if isinstance(node, ast.UnaryOp):  # Unary operations (e.g., -3)
            if type(node.op) not in ALLOWED_UNARY_OPERATORS:
                unary_msg = f"Unsupported unary operator: {type(node.op).__name__}"
                raise ValueError(unary_msg)
            return ALLOWED_UNARY_OPERATORS[type(node.op)](_eval(node.operand))
        expr_msg = f"Unsupported expression: {type(node).__name__}"
        raise TypeError(expr_msg)

    # Parse the expression into an AST and evaluate it
    try:
        parsed_expr: ast.expr = ast.parse(
            expr, mode="eval"
        ).body  # Get the body of the parsed `Expression` node
        return _eval(parsed_expr)
    except Exception as e:
        msg = f"Failed to evaluate expression '{expr}': {e}"
        raise ValueError(msg) from e


def resolve_env_token(token: str) -> str | None:
    if "@env" not in token:
        msg = f"'@env' not found in token: {token}"
        raise ValueError(msg)

    # Extract environment variable name and default value
    parts = token.replace("@env", "").strip().split(",")
    env_var_name = parts[0].strip()
    default_value = parts[1].strip() if len(parts) > 1 else None

    if not env_var_name:
        msg = f"Environment variable name missing in @env token: {token}"
        raise ValueError(msg)

    return os.getenv(env_var_name, default_value)


def resolve_format_token(token: str) -> str | None:
    try:
        if "@format" not in token:
            msg = f"'@format' not found in token: {token}"
            raise ValueError(msg)

        # Extract the inner string for @format
        formatted_string = token.replace("@format", "").strip()

        # Find and resolve all nested tokens using a regex
        tokens = re.findall(r"{(.*?)}", formatted_string)
        if not tokens:
            msg = "No tokens found in @format token"
            raise ValueError(msg)
        resolved_tokens = {token: resolve_value(token) for token in tokens}

        # Replace each nested token with its resolved value
        for tkn, resolved_value in resolved_tokens.items():
            formatted_string = formatted_string.replace(
                f"{{{tkn}}}", str(resolved_value) if resolved_value else ""
            )
    except Exception as e:
        msg = f"Invalid @format token: {token}. Error: {e}"
        raise ValueError(msg) from e
    else:
        return formatted_string


def resolve_math_token(token: str) -> int | float | None:
    if "@math" not in token:
        msg = f"'@math' not found in token: {token}"
        raise ValueError(msg)
    try:
        # Remove the @math prefix and evaluate the expression
        math_expression = token.replace("@math", "").strip()
        result = eval_ast(math_expression)
    except Exception as e:
        msg = f"Invalid @math expression: {token}. Error: {e}"
        raise ValueError(msg) from e
    else:
        return result


def resolve_value(value: str) -> str | int | float | None:
    """
    Resolves a single value.
    If the value contains a special token, it gets evaluated.
    """
    # Handle @env tokens
    if isinstance(value, str) and value.startswith("@env"):
        return resolve_env_token(value)
    # Handle @format tokens
    if isinstance(value, str) and value.startswith("@format"):
        return resolve_format_token(value)
    # Handle @math tokens
    if isinstance(value, str) and value.startswith("@math"):
        return resolve_math_token(value)
    return value


def resolve_nested_dict(
    current_dict: dict[str, Any | dict[str, Any]],
) -> dict[str, Any | dict[str, Any]]:
    """
    Recursively resolves values in the dictionary, including nested dictionaries.
    """
    resolved_dict = {}
    for key, value in current_dict.items():
        if isinstance(value, dict):
            # Recursive call for nested dictionaries
            resolved_dict[key] = resolve_nested_dict(value)
        else:
            # Resolve a single value
            resolved_dict[key] = resolve_value(value)
    return resolved_dict


def resolve_values(
    env_dict: dict[str, Any | dict[str, Any]],
) -> dict[str, Any | dict[str, Any]]:
    """
    Recursively evaluates all values in a nested dictionary and resolves special tokens:
        - @env:     Retrieves the value of an environment variable,
                    with the second token as the default value.
        - @format:  Resolves nested tokens and constructs a formatted string.
        - @math:    Evaluates a mathematical expression.

    Returns a new dictionary with all values resolved.

    Token format examples:
        - "@env ENV_VAR,default_value"
        - "@format {@env ENV_VAR1,default_value1}/{@env ENV_VAR2,default_value2}"
        - "@math 1 + 2 * 3"
    """
    # Start recursive resolution on the top-level dictionary
    return resolve_nested_dict(env_dict)
