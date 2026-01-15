import asyncio
import logging
from typing import Dict, List, Optional

from . import ConfigLines, Envs
from .daemon import LocalTaskDaemon

logger = logging.getLogger(__name__)


class TaskDaemon(LocalTaskDaemon):

    async def start(self,
                    log_level: int,
                    envs: Envs,
                    config: ConfigLines,
                    token: Optional[str]) -> None:
        await super().start(log_level,envs,config,token)
        logger.info("Sandbox Daemon in async task is started")

    async def shutdown(self) -> None:
        await super().shutdown()
        logger.info("Sandbox Daemon is shutdown")
