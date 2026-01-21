import logging

import dotenv

import pysandboxes
from pysandboxes import sandbox, sandboxes

dotenv.load_dotenv()



logger = logging.getLogger(__name__)


@sandbox
async def arun_in_sandbox():
    logger.info("Run 'arun_in_sandbox()' in sandbox")
    print(42)
    return 42


@sandbox
def run_in_sandbox():
    logger.info("Run 'run_in_sandbox()' in sandbox")
    print(42)
    return 42


async def ainit_sandbox():
    logger.error("INIT Daemon")


def init_log_level():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("aiohttp_sse_client.client").setLevel(logging.WARNING)


async def async_manager():
    for i in range(0, 2):
        async with sandboxes(init_fn=init_sandbox):
            assert await amain() == 42

#%% --------------------------------------
def init_sandbox():
    logger.debug("INIT Daemon")
    init_log_level()


async def amain():
    rc = await arun_in_sandbox()
    logger.info(f"{rc=}")
    assert rc == 42
    return rc


def main():
    import sys
    import site
    print(f"{sys.path=}")
    print(f"{sys.executable=}")
    print(f"{site.getsitepackages()=}")

    init_log_level()
    for i in range(0, 1):
        # asyncio.run(async_manager())
        # print("----------------")
        # pysandboxes.run(amain())
        # print("----------------")
        with pysandboxes.sandboxes(init_sandbox):
            main()
        print("----------------")


