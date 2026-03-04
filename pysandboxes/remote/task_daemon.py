# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Task-based daemon implementation for PySandboxes.

This module provides a simple wrapper around SSEServerDaemon that runs
in the current async task context rather than spawning separate processes.
Useful for testing and scenarios where process isolation is not required.
"""

import logging

from .sse_server_daemon import SSEServerDaemon
from ..all_rules import AllRules
from ..tools import Environ, SyncOrAsyncFunc

logger = logging.getLogger(__name__)


class TaskDaemon(SSEServerDaemon):
    """Task-based daemon that runs in the current async context.

    Extends SSEServerDaemon to provide in-process execution without
    subprocess isolation. Primarily used for testing and development.
    """

    async def _start(
            self,
            all_rules: AllRules,
            *,
            envs: Environ,
            log_level: int,
            init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        """Start the task daemon.

        Args:
            all_rules: Security rules configuration.
            envs: Environment variables.
            log_level: Logging level.
            init_fn: Optional initialization function.
        """
        await super()._start(all_rules, envs=envs, log_level=log_level, init_fn=init_fn)
        logger.info("Sandbox Daemon in async task is started")

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        """Shutdown the task daemon.

        Args:
            graceful_shutdown: Whether to perform graceful shutdown.
        """
        await super()._shutdown(graceful_shutdown)
        logger.info("Sandbox Daemon is daemon_shutdown")
