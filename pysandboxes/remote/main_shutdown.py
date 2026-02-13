import logging
import sys
import threading
import time

from pysandboxes.learning import is_learning_mode, generate_config_from_learning

logger = logging.getLogger(__name__)


async def daemon_shutdown(graceful_shutdown:bool) -> None:
    from pysandboxes.os_sandbox import async_stop_daemon, async_shutdown_daemon

    if is_learning_mode():
        generate_config_from_learning()

    if graceful_shutdown:
        # Stop all current jobs
        await async_stop_daemon(max_pending=1)  # 1 for me

        async def _delay_for_send_the_response():
            time.sleep(0.3)  # FIXME
            # And after, daemon_shutdown the daemon and exit
            await async_shutdown_daemon()

        from pysandboxes.private_loop import get_sandbox_loop
        loop = get_sandbox_loop()
        loop.create_task(_delay_for_send_the_response())
    logger.debug("Remote daemon_shutdown process executing")
