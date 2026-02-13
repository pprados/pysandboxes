import logging
from typing import Optional, Dict

from .sse_server_daemon import SSEServerDaemon
from ..all_rules import AllRules
from ..tools import SyncOrAsyncFunc
from ..sb_types import Envs

logger = logging.getLogger(__name__)


class TaskDaemon(SSEServerDaemon):

    async def start(self,
                    all_rules:AllRules,
                    *,
                    envs: Dict[str, str],
                    log_level: int,
                    init_fn: Optional[SyncOrAsyncFunc],
                    ) -> None:
        await super().start(all_rules,
                            log_level=log_level,
                            init_fn=init_fn
                            )
        logger.info("Sandbox Daemon in async task is started")

    async def shutdown(self) -> None:
        await super().shutdown()
        logger.info("Sandbox Daemon is shutdown")
