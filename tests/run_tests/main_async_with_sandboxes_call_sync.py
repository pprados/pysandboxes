
from pysandboxes import sandboxes
from .differents_usages import *

async def main():
    init_log_level()
    logger.info("--------- Async Run with sandboxes call Sync")
    for i in range(0, SIZE_OF_LOOP):
        logger.info("Use 'async with sandboxes'")
        async with sandboxes(
                init_fn=async_init_sandbox
        ):
            try:
                synchronize_function()
            except RuntimeError:
                logger.info("Impossible to mix synchronous "
                            "and asynchronous sandbox functions")
                raise

if __name__ == "__main__":
    asyncio.run(main())