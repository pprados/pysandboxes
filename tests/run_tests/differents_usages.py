import logging
import os

from pysandboxes.sandboxes_api import sandbox
from pysandboxes.tools import is_in_sandbox

logger = logging.getLogger(__name__)

def init_log_level():
    sandboxes_level = logging.DEBUG
    uvicorn_level = logging.DEBUG
    format = '[%(process)d] %(levelname)-5s %(name)s %(message)s'
    if is_in_sandbox():
        # Ident logs inside the sandbox
        root_logger = logging.getLogger()
        root_logger.setLevel(min(sandboxes_level, logging.INFO))
        root_logger.handlers[0].setFormatter(logging.Formatter("  " + format))

    logging.getLogger("asyncio").setLevel(uvicorn_level)
    logging.getLogger("uvicorn").setLevel(uvicorn_level)
    logging.getLogger("uvicorn.error").setLevel(uvicorn_level)
    logging.getLogger("aiohttp_sse_client.client").setLevel(uvicorn_level)
    logging.getLogger("Pysandboxes").setLevel(uvicorn_level)
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
    import sys
    logger.debug("************** Force Daemon exited with 99")
    # FIXME sys.exit(1)
    os._exit(99)
    return 42

@sandbox
async def arun_exit(called_pid:int):
    logger.debug("************** Force Daemon exited with 99")
    # FIXME sys.exit(1)
    os._exit(99)
    return 42

async def asynchronize_function():
    logger.info("async: Call 'asynchronize_function()'")
    # rc = await arun_in_sandbox(os.getpid())
    rc = await arun_exit(os.getpid())
    if rc != 42:
        logger.error(f"{rc=}")
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
