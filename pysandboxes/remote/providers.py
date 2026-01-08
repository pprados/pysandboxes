import asyncio

from pysandboxes.remote.abstract_start_daemon import BaseStartDaemon
from pysandboxes.remote.task_daemon import TaskDaemon

_providers = {
    "task": TaskDaemon(),
}

DEFAULT_PROVIDER = "task"


async def start_daemon(name: str = DEFAULT_PROVIDER) -> BaseStartDaemon:
    if name not in _providers:
        raise ValueError(f"Unknown daemon name: {name}")
    await _providers[name].start()
    return _providers[name]


# async def close_daemon(name:str=DEFAULT_PROVIDER):
#     if name not in _providers:
#         raise ValueError(f"Unknown daemon name: {name}")
#     await _providers[name].close()


async def main():
    # start default sandbox daemon

    server = None
    try:
        server = await start_daemon()
        await server.join()
    finally:
        if server:
            await server.close()


if __name__ == "__main__":
    asyncio.run(main())
