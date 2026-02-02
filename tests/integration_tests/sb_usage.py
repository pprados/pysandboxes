import logging

import dotenv

import pysandboxes
from pysandboxes import sandbox, sandboxes
from pysandboxes.exception import RuleError

dotenv.load_dotenv()  # FIXME: il semble y avoir un bug dans la boucle load_dotenv, car elle ne remonte pas jusqu'a elle même



logger = logging.getLogger(__name__)


@sandbox
async def arun_in_sandbox():
    logger.info("Run 'arun_in_sandbox()' in sandbox")
    print(42)
    return 42


@sandbox
def run_in_sandbox():
    logger.info("Run 'run_in_sandbox()' in sandbox")
    import io
    try:
        with io.open(".env") as f:
            pass
        assert False, "Must be stopped by pysandbox"
    except RuleError as e:
        print(e)
        pass

    try:
        with io.open("test.remove","w") as f:
            pass
        assert False, "Must be stopped by pysandbox"
    except RuleError as e:
        print(e)
        pass
    print(42)
    return 42


async def ainit_sandbox():
    logger.error("INIT Daemon")


def init_log_level():
    logging.basicConfig(level=logging.DEBUG)  # FIXME: level debug
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("aiohttp_sse_client.client").setLevel(logging.WARNING)


async def async_manager():
    for i in range(0, 2):
        async with sandboxes(init_fn=init_sandbox):
            assert await arun() == 42

#%% --------------------------------------
def init_sandbox():
    logger.debug("INIT Daemon")
    init_log_level()


async def arun():
    rc = await arun_in_sandbox()
    logger.info(f"{rc=}")
    assert rc == 42
    return rc

def run():
    rc = run_in_sandbox()
    logger.info(f"{rc=}")
    assert rc == 42
    return rc

def main():

    init_log_level()

    for i in range(0, 1):
        # asyncio.run(async_manager())
        # # print("----------------")
        with pysandboxes.sandboxes(init_sandbox):
            run()
        print("----------------")
        # pysandboxes.run(arun(),init_fn=init_sandbox)
        # print("----------------")


