import logging

from pysandboxes import sandbox

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


def init_log_level():
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("aiohttp_sse_client.client").setLevel(logging.WARNING)


def init_sandbox():
    logger.debug("INIT Daemon")
    init_log_level()


async def ainit_sandbox():
    logger.error("INIT Daemon")
