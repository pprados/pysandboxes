import asyncio
import logging
import time

import dotenv

import pysandboxes
from pysandboxes import sandboxes

from .sb_usage import run_in_sandbox, arun_in_sandbox, init_sandbox

logger = logging.getLogger(__name__)
dotenv.load_dotenv()


async def amain():
    rc = await arun_in_sandbox()
    logger.info(f"{rc=}")
    assert rc == 42
    return rc


def main():
    rc = run_in_sandbox()
    logger.info(f"{rc=}")
    assert rc == 42


async def async_manager():
    for i in range(0, 2):
        async with sandboxes(init_sandbox):
            assert await amain() == 42


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)

    for i in range(0, 1):
        asyncio.run(async_manager())
        print("----------------")
        # pysandboxes.run(amain())
        # print("----------------")
        # with pysandboxes.sandboxes(init_sandbox):
        #     main()
        # print("----------------")

    logger.debug("App terminated")
