import asyncio
import logging

from .main_async_run_and_async_init import main as main_async_run_and_async_init
from .main_async_run_and_sync_init import main as main_async_run_and_sync_init
from .main_async_with_sandboxes_call_async import (
    main as main_async_with_sandboxes_call_async,
)
from .main_async_with_sandboxes_call_sync import (
    main as main_async_with_sandboxes_call_sync,
)
from .main_sync_with_sandboxes_call_sync import (
    main as main_sync_with_sandboxes_call_sync,
)


async def async_main():
    await main_async_with_sandboxes_call_async()
    try:
        await main_async_with_sandboxes_call_sync()
    except RuntimeError:
        # Ignore. It's normal
        pass


def sync_main():
    main_async_run_and_async_init()
    main_sync_with_sandboxes_call_sync()
    main_async_run_and_sync_init()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
    )

    sync_main()
    asyncio.run(async_main())
