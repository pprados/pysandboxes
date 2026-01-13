import asyncio
import functools
import logging
from typing import Any

import dotenv

import pysandboxes
from pysandboxes import sandboxes
from pysandboxes.remote.manage_loop import sandbox_loop
from .sb_usage import run_in_sandbox, arun_in_sandbox, init_sandbox

logger = logging.getLogger(__name__)
dotenv.load_dotenv()



async def amain():
    rc = await arun_in_sandbox()
    logger.info(f"{rc=}")

def main():
    rc = run_in_sandbox()
    logger.info(f"{rc=}")


async def toto():
    for i in range(0, 2):
        # pysandboxes.run(amain())
        async with sandboxes(init_sandbox):
            await amain()


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    logging.getLogger("asyncio").setLevel(logging.INFO)

    for i in range(0,10):
        asyncio.run(toto())
        print("----------------")
        pysandboxes.run(amain())
        print("----------------")
        with sandboxes(init_sandbox):
            main()
        print("----------------")

    logger.debug("App terminated")
