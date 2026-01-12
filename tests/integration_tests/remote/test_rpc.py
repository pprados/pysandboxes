import asyncio
from typing import Iterator

import pytest

from pysandboxes import sandbox
from pysandboxes.remote.providers import start_daemon


# See https://github.com/tortoise/tortoise-orm/issues/638
@pytest.fixture(scope="session")
def event_loop():
    return asyncio.get_event_loop()


@pytest.fixture(scope="module", autouse=True)
async def before_start_daemon() -> Iterator[None]:
    # server=await start_daemon("task")  # FIXME: pb de detection de sandbox, car même interpreter
    yield
    # server.close()


@sandbox()
def sync_function(a: str, b: str) -> str:
    return f"{a} {b}"


def test_sync_function():
    result_sync = sync_function("a", b="b")
    assert result_sync == 'a b'


@sandbox()
async def async_function(a: str, b: str) -> str:
    import asyncio
    await asyncio.sleep(0.01)  # Simule une opération asynchrone
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
        sync_function_with_error(10, 0)

@sandbox(timeout=0.5)
async def async_function_with_timeout() -> str:
    await asyncio.sleep(3)
    return "This should not be returned"


@pytest.mark.skip(reason="TODO")
async def test_async_function_with_timeout():
    with pytest.raises(TimeoutError):
        await async_function_with_timeout()
