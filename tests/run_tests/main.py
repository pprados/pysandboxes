from .main_async_run_and_async_init import main as main_async_run_and_async_init
from .main_async_run_and_sync_init import main as main_async_run_and_sync_init
from .main_async_with_sandboxes_call_async import main as main_async_with_sandboxes_call_async
from .main_async_with_sandboxes_call_sync import main as main_async_with_sandboxes_call_sync
from .main_sync_with_sandboxes_call_sync import main as main_sync_with_sandboxes_call_sync

if __name__ == "__main__":
    main_async_run_and_async_init()
    main_async_run_and_sync_init()
    main_async_with_sandboxes_call_async()
    main_async_with_sandboxes_call_sync()
    main_sync_with_sandboxes_call_sync()
