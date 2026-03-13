import asyncio
import logging
import os
from asyncio import AbstractEventLoop
from pathlib import Path
from typing import AsyncGenerator, Iterator

import pytest

from pysandboxes import sandbox
from pysandboxes.os_sandbox import async_shutdown_daemon, async_start_daemon
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.remote.tools import which_command


# See https://github.com/tortoise/tortoise-orm/issues/638
@pytest.yield_fixture(scope="module")
def event_loop() -> Iterator[AbstractEventLoop]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module", autouse=True)
async def start_daemon_for_tests() -> AsyncGenerator[None, None]:
    config_path = Path(__file__).parent / "py-sandbox-test.profile"

    log_level = logging.root.getEffectiveLevel()
    all_rules = load_and_parse_config(config_path=config_path)
    all_rules = all_rules._replace(os_sandbox="firejail")
    await async_start_daemon(
        all_rules,
        envs=os.environ,
        log_level=log_level,
        init_fn=None,
    )
    yield
    await async_shutdown_daemon(graceful_shutdown=False)


@sandbox()
def sync_function(a: str, b: str) -> str:
    return f"{a} {b}"


@pytest.mark.skipif(not which_command("firejail"), reason="Install firejail")
def test_sync_function() -> None:
    result_sync = sync_function("a", b="b")
    assert result_sync == "a b"


@sandbox()
async def async_function(a: str, b: str) -> str:
    import asyncio

    await asyncio.sleep(0)  # Simule une opération asynchrone
    return f"{a} {b}"


@pytest.mark.skipif(not which_command("firejail"), reason="Install firejail")
async def test_async_function() -> None:
    result_async = await async_function("a", b="b")
    assert result_async == "a b"
