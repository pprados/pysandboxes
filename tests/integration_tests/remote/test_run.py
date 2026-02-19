import pytest

import pysandboxes
from pysandboxes.tools import mixed_sync_and_async_error
from ..sample import config_path, async_forty_two, \
    async_sanboxes, bridge_async_to_sync


def test_run() -> None:
    """
    Invoke the sandboxes.run() function
    """
    assert config_path.exists()
    pysandboxes.run(async_forty_two(), config_path=config_path)


def test_run_and_async_sanboxes() -> None:
    # An async method, call a async method with sandboxes ressource manager
    pysandboxes.run(async_sanboxes(config_path), config_path=config_path)


def test_run_and_sync_sanboxes() -> None:
    # An async method, call a sync method with sandboxes ressource manager
    # Can not be called. Use only async sandbox function.
    with pytest.raises(RuntimeError, match=mixed_sync_and_async_error):
        pysandboxes.run(bridge_async_to_sync(config_path), config_path=config_path)
