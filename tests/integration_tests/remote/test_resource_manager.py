# %% Test resource manager
import pytest  # type: ignore[import-untyped]

from pysandboxes import sandboxes
from pysandboxes.tools import mixed_sync_and_async_error

from .._env import NO_PROFILE_DNS_REASON, profile_hosts_resolvable
from ..sample import async_forty_two, config_path, init_sandbox, sync_forty_two

pytestmark = pytest.mark.skipif(not profile_hosts_resolvable(), reason=NO_PROFILE_DNS_REASON)


async def test_async_run_sandboxes_twice() -> None:
    """
    Invoke the sandbox twice to ensure that the sandbox is properly reset.
    """
    for _ in range(0, 2):
        async with sandboxes(init_sandbox, sandboxes_config=config_path):
            assert await async_forty_two() == 42


async def test_async_sandboxes_call_sync_sandbox() -> None:
    """
    Invoke the sandbox twice and call sync sandbox function
    """
    for _ in range(0, 2):
        with pytest.raises(RuntimeError, match=mixed_sync_and_async_error):
            async with sandboxes(init_sandbox, sandboxes_config=config_path):
                assert sync_forty_two() == 42


def test_sync_sandboxes_twice() -> None:
    """
    Invoke the sandbox twice to ensure that the sandbox is properly reset.
    """
    for _ in range(0, 2):
        with sandboxes(init_sandbox, sandboxes_config=config_path):
            assert sync_forty_two() == 42
