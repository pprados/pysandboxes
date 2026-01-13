import asyncio
import logging

from pysandboxes import sandbox

logger = logging.getLogger(__name__)

@sandbox
async def run_in_sandbox():
    await asyncio.sleep(0)
    logger.info("Run 'run_in_sandbox()' in sandbox")
    print(42)
    return 42

