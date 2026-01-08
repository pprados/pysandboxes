import asyncio
import logging

from pysandboxes.remote.abstract_start_daemon import BaseStartDaemon
from pysandboxes.remote.daemon import create_daemon

logger = logging.getLogger(__name__)

class TaskDaemon(BaseStartDaemon):

    async def _start(self) -> None:
        self.daemon = create_daemon()

        logger.info("Sandbox Daemon in async task")
        self.task=asyncio.create_task(self.daemon.serve())
        await asyncio.sleep(0.5)

    async def close(self) -> None:
        await self.daemon.shutdown()
        logger.info("daemon is shutdown")

    async def join(self):
        await self.task
