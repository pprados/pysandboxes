import logging

from .daemon import _TaskDaemon

logger = logging.getLogger(__name__)


class TaskDaemon(_TaskDaemon):

    async def _start(self) -> None:
        await super()._start()
        logger.warning("Sandbox Daemon in async task is started")


