from asyncio import create_task

import asyncio
import logging
from typing import Dict

from .daemon import LocalTaskDaemon, stop_daemon
from .tools import create_daemon_task

logger = logging.getLogger(__name__)


class TaskDaemon(LocalTaskDaemon):

    async def _start(self, envs: Dict[str, str], log_level: int) -> None:
        await super()._start(envs, log_level)
        logger.info("Sandbox Daemon in async task is started")

    async def shutdown(self) -> None:
        await super().shutdown()
        logger.info("Sandbox Daemon is shutdown")
