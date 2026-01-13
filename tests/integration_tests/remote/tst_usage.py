import asyncio
import logging

import dotenv

import pysandboxes
from pysandboxes import sandboxes
# from pysandboxes.sandboxes import sandboxes
from .sb_usage import run_in_sandbox, arun_in_sandbox, init_sandbox

logger = logging.getLogger(__name__)
dotenv.load_dotenv()


async def amain():
    rc = await arun_in_sandbox()
    logger.info(f"{rc=}")


def main():
    rc = run_in_sandbox()
    logger.info(f"{rc=}")


async def async_manager():
    for i in range(0, 2):
        async with sandboxes(init_sandbox):
            await amain()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    for i in range(0, 1):
        # asyncio.run(async_manager())
        # print("----------------")
        # pysandboxes.run(amain())
        # print("----------------")
        with sandboxes(init_sandbox):
            main()
        print("----------------")

    logger.debug("App terminated")
