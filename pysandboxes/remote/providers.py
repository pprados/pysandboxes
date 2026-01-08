import asyncio

from pysandboxes.remote.abstract_start_daemon import BaseStartDaemon
from pysandboxes.remote.task_daemon import TaskDaemon
from pysandboxes.remote.tools import set_is_in_sandbox

_providers={
    "task":TaskDaemon(),
}

async def start_daemon(name:str="task") -> BaseStartDaemon:
    if name not in _providers:
        raise ValueError(f"Unknown daemon name: {name}")
    await _providers[name].start()
    return _providers[name]

async def close_daemon(name:str):
    if name not in _providers:
        raise ValueError(f"Unknown daemon name: {name}")
    await _providers[name].close()


async def main():
    # start default daemon

    server=await start_daemon()
    await server.join()

if __name__ == "__main__":
    asyncio.run(main())