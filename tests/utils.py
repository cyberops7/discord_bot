from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def async_test(func: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
    """Wrapper for pytest.mark.asyncio that handles Pyrefly type issues"""
    return pytest.mark.asyncio(func)  # pyrefly: ignore[56]
