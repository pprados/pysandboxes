import asyncio
import logging
from pathlib import Path
from typing import Iterator

import pytest

from pysandboxes.os_sandbox import start_daemon, \
    shutdown_daemon
from pysandboxes.py_sandbox import read_and_parse_config
from pysandboxes import sandbox


# See https://github.com/tortoise/tortoise-orm/issues/638
@pytest.yield_fixture(scope='module')
def event_loop(request):
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="module", autouse=True)
async def start_daemon_for_tests() -> Iterator[None]:
    config_path = Path(__file__).parent.parent / "py-sandbox-test.profile"

    log_level = logging.root.getEffectiveLevel()
    all_rules = read_and_parse_config(config_path=config_path)

    start_daemon(all_rules,
                 log_level,
                 init_fn=None,
                 timeout=2,
                 )
    yield
    shutdown_daemon()


@sandbox()
def sync_function(a: str, b: str) -> str:
    return f"{a} {b}"


def test_sync_function():
    result_sync = sync_function("a", b="b")
    assert result_sync == 'a b'


@sandbox()
async def async_function(a: str, b: str) -> str:
    import asyncio
    await asyncio.sleep(0)  # Simule une opération asynchrone
    return f"{a} {b}"


async def test_async_function():
    result_async = await async_function("a", b="b")
    assert result_async == 'a b'


@sandbox()
def sync_function_with_error(a: int, b: int) -> str:
    return a / b


def test_sync_function_with_error():
    with pytest.raises(ZeroDivisionError):
        sync_function_with_error(10, 0)


@sandbox()
async def async_function_with_error(a: int, b: int) -> str:
    return a / b


async def test_async_function_with_error():
    with pytest.raises(ZeroDivisionError):
        await async_function_with_error(10, 0)


@sandbox(timeout=0.5)
async def async_function_with_timeout() -> str:
    await asyncio.sleep(3)
    return "This should not be returned"


@pytest.mark.skip(reason="TODO")
async def test_async_function_with_timeout():
    with pytest.raises(TimeoutError):
        await async_function_with_timeout()
