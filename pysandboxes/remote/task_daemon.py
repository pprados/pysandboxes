import logging
from typing import Optional

from .run_daemon import LocalTaskDaemon
from ..tools import SyncOrAsyncFunc
from ..types import ConfigLines, Envs

logger = logging.getLogger(__name__)


class TaskDaemon(LocalTaskDaemon):

    async def start(self,
                    log_level: int,
                    envs: Envs,
                    config: ConfigLines,
                    init_fn: Optional[SyncOrAsyncFunc],
                    token: Optional[str]) -> None:
        await super().start(log_level, envs, config, init_fn, token)
        logger.info("Sandbox Daemon in async task is started")

    async def shutdown(self) -> None:
        await super().shutdown()
        logger.info("Sandbox Daemon is shutdown")
