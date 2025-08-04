from collections.abc import Awaitable, Callable

import pytest


def async_test(func: Callable[..., Awaitable[None]]) -> Callable[..., Awaitable[None]]:
    """Wrapper for pytest.mark.asyncio that handles Pyre type issues"""
    return pytest.mark.asyncio(func)  # type: ignore[56]
