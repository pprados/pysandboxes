
import pysandboxes
from .differents_usages import *

async def main():
    init_log_level()
    for i in range(0, 1):
        logger.info("Use 'async with sandboxes'")
        async with sandboxes(
                init_fn=async_init_sandbox
        ):
            try:
                synchronize_function()
            except RuntimeError:
                logger.info("Impossible to mix synchronous "
                            "and asynchronous sandbox functions")
                pass

if __name__ == "__main__":
    asyncio.run(main())