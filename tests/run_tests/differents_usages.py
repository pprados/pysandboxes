import asyncio
import logging
import os

from pysandboxes.sandboxes_api import sandbox, sandboxes

logger = logging.getLogger(__name__)

def init_log_level():
    sandboxes_level = logging.DEBUG
    format = '%(levelname)-5s [%(process)d] %(message)s'
    logging.basicConfig(
        level=min(sandboxes_level, logging.INFO),
        format=format
    )
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("aiohttp_sse_client.client").setLevel(logging.WARNING)
    logging.getLogger("Pysandboxes").setLevel(sandboxes_level)
    logging.getLogger("pysandboxes").setLevel(sandboxes_level)
    logger.setLevel(logging.INFO)

def sync_init_sandbox():
    logger.debug("sync: 'sync_init_sandbox()' called")
    init_log_level()

async def async_init_sandbox():
    logger.debug("sync: 'async_init_sandbox()' called")
    init_log_level()

@sandbox
async def arun_in_sandbox(called_pid:int):
    logger.info("async: annotated 'arun_in_sandbox()' called in a sandbox")
    assert called_pid != os.getpid()
    await asyncio.sleep(2)
    return 42

async def asynchronize_function():
    logger.info("async: Call 'asynchronize_function()'")
    rc = await arun_in_sandbox(os.getpid())
    assert rc == 42

@sandbox
def run_in_sandbox(called_pid:int):
    logger.info("sync: annotated 'run_in_sandbox()' called in a sandbox")
    assert called_pid != os.getpid()
    return 42

def synchronize_function():
    logger.info("sync: Call 'synchronize_function()'")
    rc = run_in_sandbox(os.getpid())
    assert rc == 42
