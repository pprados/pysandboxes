import asyncio
import logging
import os
from asyncio import AbstractEventLoop
from pathlib import Path
from typing import AsyncGenerator, Iterator

import pytest  # type: ignore[import-untyped]
import pytest_asyncio  # type: ignore[import-untyped]

from pysandboxes import sandbox
from pysandboxes._os_sandbox import async_shutdown_daemon, async_start_daemon
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.py_sandbox import load_and_parse_config
from pysandboxes.remote.tools import which_command

_BWRAP_SKIP_REASON = "bwrap not installed"

# py-sandbox-test.profile includes net= rules, which would otherwise enable
# --unshare-net + slirp4netns + iptables (needs CAP_NET_ADMIN). For a portable
# integration test we force host network so the suite passes without root.
_BWRAP_SHARE_NET = ImmutableDict({"share-net": "yes"})


def _bwrap_integration_ready() -> bool:
    return bool(which_command("bwrap"))


# See https://github.com/tortoise/tortoise-orm/issues/638
@pytest.fixture(scope="module")
def event_loop() -> Iterator[AbstractEventLoop]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="module", autouse=True)
async def start_daemon_for_tests() -> AsyncGenerator[None, None]:
    if not _bwrap_integration_ready():
        yield
        return
    config_path = Path(__file__).parent / "py-sandbox-test.profile"

    log_level = logging.root.getEffectiveLevel()
    all_rules = load_and_parse_config(config_path=config_path)
    all_rules = all_rules._replace(
        os_sandbox="bwrap",
        os_sandbox_params=_BWRAP_SHARE_NET,
    )
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


@pytest.mark.skipif(not _bwrap_integration_ready(), reason=_BWRAP_SKIP_REASON)
def test_sync_function() -> None:
    result_sync = sync_function("a", b="b")
    assert result_sync == "a b"


@sandbox()
async def async_function(a: str, b: str) -> str:
    import asyncio

    await asyncio.sleep(0)
    return f"{a} {b}"


@pytest.mark.skipif(not _bwrap_integration_ready(), reason=_BWRAP_SKIP_REASON)
async def test_async_function() -> None:
    result_async = await async_function("a", b="b")
    assert result_async == "a b"
