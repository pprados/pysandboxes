"""Daemon shutdown handler for PySandboxes.

This module handles the graceful shutdown of sandbox daemons, including
learning mode cleanup and rule generation when the daemon terminates.
"""

import logging
import time

from pysandboxes.learning import generate_config_from_learning, is_learning_mode
from pysandboxes.remote.parameters import POLLING_DELAY

logger = logging.getLogger(__name__)


async def daemon_shutdown(graceful_shutdown: bool) -> None:
    """Handle daemon shutdown and cleanup.

    Args:
        graceful_shutdown: Whether to perform graceful shutdown with learning cleanup.
    """
    from pysandboxes.os_sandbox import async_shutdown_daemon, async_stop_daemon

    global _current_daemon
    if is_learning_mode():
        generate_config_from_learning()

    if graceful_shutdown:
        # Stop all current jobs
        await async_stop_daemon(max_pending=1)  # 1 for me

        async def _delay_for_send_the_response() -> None:
            time.sleep(POLLING_DELAY)
            # And after, daemon_shutdown the daemon and exit
            await async_shutdown_daemon()

        from pysandboxes.private_loop import get_sandbox_loop

        loop = get_sandbox_loop()
        loop.create_task(_delay_for_send_the_response())
    logger.debug("Remote daemon_shutdown process executing")
