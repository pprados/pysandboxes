import asyncio
import logging
import os
import sys

from pysandboxes.remote.process_daemon import ProcessDaemon
from .abstract_start_daemon import BaseStartDaemon
from .task_daemon import TaskDaemon

_providers = {
    "task": TaskDaemon(),  # For debug. Impossible to activate sandbox in this mode.
    "process": ProcessDaemon(),
}

DEFAULT_PROVIDER = "process"


async def start_daemon(name: str = DEFAULT_PROVIDER) -> BaseStartDaemon:
    if name not in _providers:
        raise ValueError(f"Unknown daemon name: {name}")
    await _providers[name].start()
    return _providers[name]


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
        sys.exit(asyncio.run(main()))
    except SystemExit as e:
        sys.exit(e.code)
    except KeyboardInterrupt:
        sys.exit(0)
