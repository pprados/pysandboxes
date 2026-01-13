import asyncio
import logging
import threading

from pysandboxes.remote.bwrap_daemon import BWrapDaemon
from pysandboxes.remote.firejail_daemon import FireJailDaemon
from .abstract_start_daemon import BaseDaemon
from .subprocess_daemon import SubProcessDaemon
from .task_daemon import TaskDaemon

logger = logging.getLogger(__name__)

providers = {
    "task": TaskDaemon(),  # For debug. Impossible to activate sandbox in this mode.
    "subprocess": SubProcessDaemon(),
    "bwrap": BWrapDaemon(),
    "firejail": FireJailDaemon(),
    # TODO: podman, https://www.redhat.com/en/blog/podman-inside-container https://www.redhat.com/en/blog/podman-inside-kubernetes
    #  docker, lxc, ...
    # docker alternative
    # TODO: external started daemon
    # TODO https://github.com/igo95862/bubblejail
}

DEFAULT_OS_SANDBOX = "firejail"


async def async_start_daemon(name: str, log_level: int) -> BaseDaemon:
    if name not in providers:
        raise ValueError(f"Unknown daemon name: {name}")
    await providers[name].start(log_level)
    return providers[name]

async def async_shutdown_daemon(name: str):
    await providers[name].shutdown()

# TODO: def shutdown_daemon(name:str)

def start_daemon(name: str, log_level: int) -> None:
    def _run_in_thread():
        logger.debug("Sync start sub-process daemon")
        coro = async_start_daemon(name, log_level)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        else:
            return asyncio.ensure_future(coro)

    thread = threading.Thread(target=_run_in_thread, daemon=True)
    thread.start()
