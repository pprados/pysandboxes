# %% Test exception
import pytest

from integration_tests.sample import init_sandbox, config_path
from pysandboxes.sandboxes import sandbox, sandboxes


@sandbox
async def async_with_exception():
    raise Exception("This is an exception")


@sandbox
def sync_with_exception():
    raise Exception("This is an exception")


def test_catch_sync_with_exception():
    with sandboxes(init_sandbox, config_path=config_path):
        with pytest.raises(Exception):
            sync_with_exception()


async def test_catch_async_with_exception():
    async with sandboxes(init_sandbox, config_path=config_path):
        with pytest.raises(Exception):
            await async_with_exception()


