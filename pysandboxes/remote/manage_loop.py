import asyncio
import functools
import logging
import threading
import weakref
from _weakref import ReferenceType
from asyncio import AbstractEventLoop
from typing import Optional, Any, Callable

logger = logging.getLogger(__name__)

_background_loop_ref:ReferenceType[AbstractEventLoop] = None

_lock = threading.Lock()

def set_sandbox_loop(loop:AbstractEventLoop) -> None:
    global _background_loop_ref
    _background_loop_ref = weakref.ref(loop)

def _ensure_background_loop(new_loop:bool = False) -> Optional[AbstractEventLoop]:
    """Crée une boucle d'arrière-plan dans un thread dédié si nécessaire"""
    global _background_loop_ref

    if _background_loop_ref is not None:
        loop = _background_loop_ref()
        if loop is not None and loop.is_running():
            return loop
    if not new_loop:
        return None


    with _lock:
        # Double check
        if _background_loop_ref is not None:
            loop = _background_loop_ref()
            if loop is not None and loop.is_running():
                return loop

        logger.debug("Create a private event loop")
        loop = asyncio.new_event_loop()
        loop.set_debug(True)  # FIXME: remove this line in production
        _background_loop_ref = weakref.ref(loop)
        asyncio.set_event_loop(loop)

        start_event = threading.Event()
        def _start_background_loop() -> None:
            """Start the background loop forever"""
            asyncio.set_event_loop(loop)
            start_event.set()
            loop.run_forever()

        thread = threading.Thread(
            target=_start_background_loop,
            daemon=True,
            name="Sandbox Private loop"
        )
        thread.start()
        start_event.wait()
    return loop


def sandbox_loop(func: Callable[..., Any]) -> Callable[..., Any]:

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        old_loop = None
        try:
            # old_loop = asyncio.get_event_loop()
            old_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        loop = get_sandbox_loop()
        asyncio.set_event_loop(loop)
        # x=asyncio.get_running_loop()  # FIXME
        x=asyncio.get_event_loop()  # FIXME
        # assert x == loop

        result = func(*args, **kwargs)

        asyncio.set_event_loop(old_loop)
        return result

    return wrapper

def reset_sandbox_loop():
    global _background_loop_ref
    with _lock:
        _background_loop_ref = None

def get_sandbox_loop() -> AbstractEventLoop:
    """Lance le serveur dans la boucle appropriée"""

    try:
        # # Reuse private loop?
        loop = _ensure_background_loop(new_loop=True)  # TODO: vérifer new_loop
        if loop:
            # logger.debug("Reuse the private event loop")
            return loop
        # Try to use the active loop
        #loop = asyncio.get_event_loop()
        loop = asyncio.get_running_loop()
        # logger.debug("Use the active loop")
        return loop
    except RuntimeError:
        # Create a private loop
        # logger.debug("Creating a private event loop")
        return _ensure_background_loop(new_loop=True) # FIXME: propablement plus possible
