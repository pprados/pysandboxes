# %% Test exception
import logging
from pathlib import Path
from typing import NoReturn

import pytest

from pysandboxes import sandbox, sandboxes

config_path = Path(__file__).parent / "py-sandbox-test.profile"
logger = logging.getLogger(__name__)


def init_sandbox() -> None:
    logger.info("init_sandbox called")


@sandbox
async def async_with_exception() -> NoReturn:
    raise ValueError("This is an exception")


@sandbox
def sync_with_exception() -> NoReturn:
    raise ValueError("This is an exception")


def test_catch_sync_with_exception() -> None:
    with sandboxes(init_sandbox, sandboxes_config=config_path):
        with pytest.raises(ValueError):
            sync_with_exception()


async def test_catch_async_with_exception() -> None:
    async with sandboxes(init_sandbox, sandboxes_config=config_path):
        with pytest.raises(ValueError):
            await async_with_exception()
