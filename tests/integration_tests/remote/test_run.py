import pytest  # type: ignore[import-untyped]

import pysandboxes
from pysandboxes.tools import mixed_sync_and_async_error

from .._env import NO_PROFILE_DNS_REASON, profile_hosts_resolvable
from ..sample import async_forty_two, async_sanboxes, bridge_async_to_sync, config_path

pytestmark = pytest.mark.skipif(not profile_hosts_resolvable(), reason=NO_PROFILE_DNS_REASON)


def test_run() -> None:
    """
    Invoke the sandboxes.run() function

    The return value is asserted: `run()` is documented as a replacement for
    `asyncio.run()`, and a caller that ignores what it returns cannot see it
    hand back something else.
    """
    assert config_path.exists()
    assert pysandboxes.run(async_forty_two(), sandboxes_config=config_path) == 42


def test_run_and_async_sanboxes() -> None:
    # An async method, call a async method with sandboxes resource manager
    pysandboxes.run(async_sanboxes(config_path), sandboxes_config=config_path)


def test_run_and_sync_sanboxes() -> None:
    # An async method, call a sync method with sandboxes resource manager
    # Can not be called. Use only async sandbox function.
    with pytest.raises(RuntimeError, match=mixed_sync_and_async_error):
        pysandboxes.run(bridge_async_to_sync(config_path), sandboxes_config=config_path)
