
import pysandboxes
from .differents_usages import *

async def main():
    init_log_level()
    for i in range(0, 1):
        logger.info("Use 'async with sandboxes'")
        async with sandboxes(
                init_fn=async_init_sandbox
        ):
            await asynchronize_function()

if __name__ == "__main__":
    asyncio.run(main())