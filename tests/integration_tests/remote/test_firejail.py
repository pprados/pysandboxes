import asyncio
import logging
from pathlib import Path
from typing import Iterator

import pytest

from pysandboxes import sandbox
from pysandboxes.py_sandbox import get_config_path, read_and_parse_config
from pysandboxes.os_sandboxes import start_daemon, \
    shutdown_daemon
from pysandboxes.remote.tools import which_command


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
    config = get_config_path(config_path).read_text().splitlines()
    config, _, os_sandbox, *_ = read_and_parse_config(config=config)
    config.append("--os-sandbox=firejail")
    start_daemon("firejail",
                 log_level,
                 config,
                 timeout=15,
                 )
    yield
    shutdown_daemon()


@sandbox()
def sync_function(a: str, b: str) -> str:
    return f"{a} {b}"


@pytest.mark.skipif(not which_command("firejail"),
                    reason="Install firejail")
def test_sync_function():
    result_sync = sync_function("a", b="b")
    assert result_sync == 'a b'


@sandbox()
async def async_function(a: str, b: str) -> str:
    import asyncio
    await asyncio.sleep(0)  # Simule une opération asynchrone
    return f"{a} {b}"


@pytest.mark.skipif(not which_command("firejail"),
                    reason="Install firejail")
async def test_async_function():
    result_async = await async_function("a", b="b")
    assert result_async == 'a b'

