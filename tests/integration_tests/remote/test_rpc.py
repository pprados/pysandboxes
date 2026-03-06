import logging
import os
from pathlib import Path
from typing import Any, Iterator

import pytest

from pysandboxes import sandbox
from pysandboxes.os_sandbox import shutdown_daemon, start_daemon
from pysandboxes.py_sandbox import load_and_parse_config


@pytest.hookimpl(tryfirst=True)
def pytest_fixture_post_finalizer(fixturedef: Any, request: Any) -> None:
    pass


@pytest.fixture(scope="module", autouse=True)
def start_daemon_for_tests() -> Iterator[None]:
    config_path = Path(__file__).parent.parent / "py-sandbox-test.profile"

    log_level = logging.root.getEffectiveLevel()
    all_rules = load_and_parse_config(config_path=config_path)
    start_daemon(
        all_rules,
        envs=os.environ,
        log_level=log_level,
        init_fn=None,
    )
    yield
    shutdown_daemon(graceful_shutdown=False)


@sandbox()
def sync_function(a: str, b: str) -> str:
    return f"{a} {b}"


# FIXME: RichHandler if possible. Bug sur test_sync_function
def test_sync_function() -> None:
    result_sync = sync_function("a", b="b")
    assert result_sync == "a b"


@sandbox()
async def async_function(a: str, b: str) -> str:
    import asyncio

    await asyncio.sleep(0)  # Simule une opération asynchrone
    return f"{a} {b}"


async def test_async_function() -> None:
    result_async = await async_function("a", b="b")
    assert result_async == "a b"


@sandbox()
def sync_function_with_error(a: int, b: int) -> float:
    return a / b


def test_sync_function_with_error() -> None:
    with pytest.raises(ZeroDivisionError):
        sync_function_with_error(10, 0)


@sandbox()
async def async_function_with_error(a: int, b: int) -> float:
    return a / b


async def test_async_function_with_error() -> None:
    with pytest.raises(ZeroDivisionError):
        await async_function_with_error(10, 0)
