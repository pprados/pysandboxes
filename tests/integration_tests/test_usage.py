import logging
import sys
from pathlib import Path
from typing import Tuple

import _pytest
import pytest

from pysandboxes import sandbox, sandboxes, run

logger = logging.getLogger(__name__)

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



# %% Test Sandbox
async def test_async_sandboxes() -> None:
    """
    Invoke the sandbox twice to ensure that the sandbox is properly reset.
    """
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    assert config_path.exists()
    for i in range(0, 2):
        async with sandboxes(init_sandbox, config_path=config_path):
            assert await async_forty_two() == 42


@pytest.mark.skip(reason="Not working")
async def test_async_sandboxes_call_sync_sandbox() -> None:
    """
    Invoke the sandbox twice and call sync sandbox function
    """
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    assert config_path.exists()
    for i in range(0, 2):
        async with sandboxes(init_sandbox, config_path=config_path):
            assert sync_forty_two() == 42


def test_sync_sandboxes() -> None:
    """
    Invoke the sandbox twice to ensure that the sandbox is properly reset.
    """
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    assert config_path.exists()
    for i in range(0, 2):
        with sandboxes(init_sandbox, config_path=config_path):
            assert sync_forty_two() == 42


def sync_sanboxes(config_path:Path) -> None:
    with sandboxes(init_sandbox, config_path=config_path):
        assert async_forty_two() == 42

async def async_sanboxes(config_path:Path) -> None:
    async with sandboxes(init_sandbox, config_path=config_path):
        assert await async_forty_two() == 42

async def _bridge_async_to_sync(config_path:Path) -> None:
    sync_sanboxes(config_path)

# %% run
def test_run() -> None:
    """
    Invoke the sandboxes.run() function
    """
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    assert config_path.exists()
    run(async_forty_two(), config_path=config_path)

def test_run_and_async_sanboxes() -> None:
    # An async method, call a async method with sandboxes ressource manager
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    assert config_path.exists()
    run(async_sanboxes(config_path), config_path=config_path)

@pytest.mark.skip(reason="Not working")
def test_run_and_sync_sanboxes() -> None:
    # An async method, call a sync method with sandboxes ressource manager
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    assert config_path.exists()
    run(_bridge_async_to_sync(config_path), config_path=config_path)

#%% Test print
@sandbox
def sync_print_stdin_stdout():
    print("hello")
    print("world", file=sys.stderr)

@sandbox
def async_print_stdin_stdout():
    print("hello")
    print("world", file=sys.stderr)

def test_sync_catch_stdout_and_stderr(capsys: _pytest.capture.CaptureFixture):
    """
    Catch stdin and stdout from the sandbox, in the main process
    """
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    with sandboxes(init_sandbox, config_path=config_path):
        sync_print_stdin_stdout()
        captured_output = capsys.readouterr()
        assert captured_output.out == "hello\n"
        assert captured_output.err == "world\n"

@pytest.mark.skip(reason="Not working")
async def test_async_catch_stdout_and_stderr(capsys: _pytest.capture.CaptureFixture):
    """
    Catch stdin and stdout from the sandbox, in the main process
    """
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    async with sandboxes(init_sandbox, config_path=config_path):
        await async_print_stdin_stdout()
        captured_output = capsys.readouterr()
        assert captured_output.out == "hello\n"
        assert captured_output.err == "world\n"

# %% Test exception
@sandbox
async def async_with_exception():
    raise Exception("This is an exception")

@sandbox
def sync_with_exception():
    raise Exception("This is an exception")

def test_catch_sync_with_exception():
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    with sandboxes(init_sandbox, config_path=config_path):
        with pytest.raises(Exception):
            sync_with_exception()

async def test_catch_async_with_exception():
    config_path = Path(__file__).parent / "py-sandbox-test.profile"
    async with sandboxes(init_sandbox, config_path=config_path):
        with pytest.raises(Exception):
            await async_with_exception()

# %% Process life cycle
@pytest.mark.skip(reason="Not working")
def test_kill_child_process():
    raise NotImplementedError

@pytest.mark.skip(reason="Not working")
def test_kill_parent_process():
    raise NotImplementedError

