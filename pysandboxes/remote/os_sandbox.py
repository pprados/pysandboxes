import asyncio
import logging
import sys

from pysandboxes.remote.bwrap_daemon import BWrapDaemon
from pysandboxes.remote.firejail_daemon import FireJailDaemon
from .abstract_start_daemon import BaseStartDaemon
from .subprocess_daemon import SubProcessDaemon
from .task_daemon import TaskDaemon

providers = {
    "task": TaskDaemon(),  # For debug. Impossible to activate sandbox in this mode.
    "subprocess": SubProcessDaemon(),
    "bwrap": BWrapDaemon(),
    "firejail": FireJailDaemon(),
    # TODO: podman, https://www.redhat.com/en/blog/podman-inside-container https://www.redhat.com/en/blog/podman-inside-kubernetes
    #  docker, lxc, ...
    # docker alternative
}

DEFAULT_OS_SANDBOX = "firejail"


async def start_daemon(name: str = DEFAULT_OS_SANDBOX) -> BaseStartDaemon:
    if name not in providers:
        raise ValueError(f"Unknown daemon name: {name}")
    await providers[name].start()
    return providers[name]


async def main():
    # start default sandbox daemon

    logging.basicConfig(level=logging.INFO)
    server = None
    try:
        server = await start_daemon()
        return await server.join()
    finally:
        if server:
            await server.close()


if __name__ == "__main__":
    try:
        # import dotenv
        # dotenv.load_dotenv()  # FIXME
        sys.exit(asyncio.run(main()))
    except SystemExit as e:
        sys.exit(e.code)
    except KeyboardInterrupt:
        sys.exit(0)
