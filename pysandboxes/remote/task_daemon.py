import logging
import os
from typing import Dict, Optional

from ..all_rules import AllRules
from ..tools import SyncOrAsyncFunc, Environ
from .sse_server_daemon import SSEServerDaemon

logger = logging.getLogger(__name__)


class TaskDaemon(SSEServerDaemon):
    async def _start(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: Optional[SyncOrAsyncFunc],
    ) -> None:
        await super()._start(all_rules,
                             envs=envs,
                             log_level=log_level,
                             init_fn=init_fn)
        logger.info("Sandbox Daemon in async task is started")

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        await super()._shutdown(graceful_shutdown)
        logger.info("Sandbox Daemon is daemon_shutdown")
