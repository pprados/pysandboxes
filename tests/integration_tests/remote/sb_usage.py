import asyncio
import logging
import time

from pysandboxes.remote.sandboxes import sandbox

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

def init_sandbox():
    logger.error("INIT Daemon")

async def ainit_sandbox():
    logger.error("INIT Daemon")
