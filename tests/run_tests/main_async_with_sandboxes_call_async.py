import asyncio

import pysandboxes
from .differents_usages import *

async def main():
    init_log_level()
    for i in range(0, 1):
        logger.info("Use 'async with sandboxes'")
        async with sandboxes(
                init_fn=async_init_sandbox,
                graceful_shutdown=True,
        ):
            await asynchronize_function()
            os.kill(os.getpid(), 2)  # FIXME

if __name__ == "__main__":
    asyncio.run(main())