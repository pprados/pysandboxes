# %% Test exception
from typing import NoReturn

import pytest

from pysandboxes import sandbox, sandboxes

from ..sample import config_path, init_sandbox


@sandbox
async def async_with_exception() -> NoReturn:
    raise Exception("This is an exception")


@sandbox
def sync_with_exception() -> NoReturn:
    raise Exception("This is an exception")


def test_catch_sync_with_exception() -> None:
    with sandboxes(init_sandbox, sandboxes_config=config_path):
        with pytest.raises(Exception):
            sync_with_exception()


async def test_catch_async_with_exception() -> None:
    async with sandboxes(init_sandbox, sandboxes_config=config_path):
        with pytest.raises(Exception):
            await async_with_exception()
