import logging
from typing import Dict

from .daemon import _LocalTaskDaemon

logger = logging.getLogger(__name__)


class TaskDaemon(_LocalTaskDaemon):

    async def _start(self,envs:Dict[str,str],log_level:int) -> None:
        await super()._start()
        logger.warning("Sandbox Daemon in async task is started")


