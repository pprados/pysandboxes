import asyncio

from pysandboxes import sandboxes

from .differents_usages import *


async def main():
    init_log_level()
    logger.info("--------- Async Run with sandboxes call Async")
    for i in range(0, SIZE_OF_LOOP):
        logger.info("Use 'async with sandboxes'")
        async with sandboxes(
            init_fn=async_init_sandbox,
            graceful_shutdown=True,
        ):
            await asynchronize_function()
        logger.debug("'main()' terminate'")


if __name__ == "__main__":
    asyncio.run(main())
