import logging
from pathlib import Path

import pytest

from pysandboxes import sandbox, sandboxes, run

logger = logging.getLogger(__name__)


@sandbox
async def arun_in_sandbox():
    print(42)
    return 42


@sandbox
def run_in_sandbox():
    print(42)
    return 42


async def async_forty_two():
    rc = await arun_in_sandbox()
    assert rc == 42
    return rc


def forty_two():
    rc = run_in_sandbox()
    assert rc == 42
    return rc


def init_sandbox():
    pass



async def test_async_sandboxes():
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    assert config_path.exists()
    for i in range(0, 2):
        async with sandboxes(init_sandbox, config_path=config_path):
            assert await async_forty_two() == 42


def test_sync_sandboxes():
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    assert config_path.exists()
    for i in range(0, 2):
        with sandboxes(init_sandbox, config_path=config_path):
            assert forty_two() == 42


def sync_sanboxes(config_path:Path):
    with sandboxes(init_sandbox, config_path=config_path):
        assert async_forty_two() == 42

async def async_sanboxes(config_path:Path):
    async with sandboxes(init_sandbox, config_path=config_path):
        assert await async_forty_two() == 42

chang
def test_run():
    # run with an async method
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    assert config_path.exists()
    run(async_forty_two(), config_path=config_path)

def test_run_and_async_sanboxes():
    # An async method, call a async method with sandboxes ressource manager
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    assert config_path.exists()
    run(async_sanboxes(config_path), config_path=config_path)

async def _bridge(config_path:Path):
    sync_sanboxes(config_path)

@pytest.mark.skip(reason="Not working")
def test_run_and_sync_sanboxes():
    # An async method, call a sync method with sandboxes ressource manager
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    assert config_path.exists()
    run(_bridge(config_path), config_path=config_path)
