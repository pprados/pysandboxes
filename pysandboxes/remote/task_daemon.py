import logging
from typing import Optional

from .local_task_daemon import LocalTaskDaemon
from ..all_rules import AllRules
from ..tools import SyncOrAsyncFunc
from ..types import Envs

logger = logging.getLogger(__name__)


class TaskDaemon(LocalTaskDaemon):

    async def start(self,
                    all_rules:AllRules,
                    *,
                    log_level: int,
                    envs: Optional[Envs],
                    init_fn: Optional[SyncOrAsyncFunc],
                    ) -> None:
        await super().start(all_rules,
                            log_level=log_level,
                            envs=envs,
                            init_fn=init_fn
                            )
        logger.info("Sandbox Daemon in async task is started")

    async def shutdown(self) -> None:
        await super().shutdown()
        logger.info("Sandbox Daemon is shutdown")
