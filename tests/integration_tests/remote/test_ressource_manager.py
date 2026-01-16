# %% Test ressource manager
import pytest

from pysandboxes import sandboxes
from pysandboxes.remote.os_sandboxes import _mixed_sync_and_async_error
from .sample import async_forty_two, sync_forty_two, init_sandbox, config_path


async def test_async_run_sandboxes_twice() -> None:
    """
    Invoke the sandbox twice to ensure that the sandbox is properly reset.
    """
    for i in range(0, 2):
        async with sandboxes(init_sandbox, config_path=config_path):
            assert await async_forty_two() == 42


async def test_async_sandboxes_call_sync_sandbox() -> None:
    """
    Invoke the sandbox twice and call sync sandbox function
    """
    for i in range(0, 2):
        with pytest.raises(RuntimeError, match=_mixed_sync_and_async_error):
            async with sandboxes(init_sandbox, config_path=config_path):
                assert sync_forty_two() == 42


def test_sync_sandboxes_twice() -> None:
    """
    Invoke the sandbox twice to ensure that the sandbox is properly reset.
    """
    for i in range(0, 2):
        with sandboxes(init_sandbox, config_path=config_path):
            assert sync_forty_two() == 42


