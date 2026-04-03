import asyncio
import logging
import os
from asyncio import AbstractEventLoop
from pathlib import Path
from typing import Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes import sandbox
from pysandboxes._os_sandbox import shutdown_daemon, start_daemon
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.remote.tools import unshare_user_namespace_available


# See https://github.com/tortoise/tortoise-orm/issues/638
@pytest.fixture(scope="module")
def event_loop() -> Iterator[AbstractEventLoop]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module", autouse=True)
def start_daemon_for_tests() -> Iterator[None]:
    """Start daemon on the sandbox private loop so sync and async tests both work."""
    config_path = Path(__file__).parent / "py-sandbox-test.profile"

    log_level = logging.root.getEffectiveLevel()
    all_rules = load_and_parse_config(config_path=config_path)
    all_rules = all_rules._replace(os_sandbox="unshare")

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


@pytest.mark.skipif(
    not unshare_user_namespace_available(),
    reason="unshare/slirp4netns missing or user namespaces not permitted (e.g. in containers)",
)
def test_sync_function() -> None:
    result_sync = sync_function("a", b="b")
    assert result_sync == "a b"


@sandbox()
async def async_function(a: str, b: str) -> str:
    import asyncio

    await asyncio.sleep(0)  # Simulate async operation
    return f"{a} {b}"


@pytest.mark.skipif(
    not unshare_user_namespace_available(),
    reason="unshare/slirp4netns missing or user namespaces not permitted (e.g. in containers)",
)
async def test_async_function() -> None:
    result_async = await async_function("a", b="b")
    assert result_async == "a b"
