import asyncio
import sys
from pathlib import Path

import logging

from pysandboxes import sandbox, sandboxes

logger = logging.getLogger(__name__)

config_path = Path(__file__).parent / "py-sandbox-test.profile"
assert config_path.exists()


def init_sandbox() -> None:
    pass  # TODO: implémenter et invoquer



@sandbox
async def arun_in_sandbox() -> int:
    print(42)
    return 42


@sandbox
def run_in_sandbox() -> int:
    print(42)
    return 42


async def async_forty_two() -> int:
    rc = await arun_in_sandbox()
    assert rc == 42
    return rc


def sync_forty_two() -> int:
    rc = run_in_sandbox()
    assert rc == 42
    return rc


def sync_sanboxes(config_path: Path) -> None:
    with sandboxes(init_sandbox, config_path=config_path):
        assert sync_forty_two() == 42


async def async_sanboxes(config_path: Path) -> None:
    async with sandboxes(init_sandbox, config_path=config_path):
        assert await async_forty_two() == 42


async def bridge_async_to_sync(config_path: Path) -> None:
    await asyncio.sleep(0)
    sync_sanboxes(config_path)

@sandbox
def sync_print_stdin_stdout():
    print("hello")
    print("world", file=sys.stderr)


@sandbox
async def async_print_stdin_stdout():
    print("hello")
    print("world", file=sys.stderr)


