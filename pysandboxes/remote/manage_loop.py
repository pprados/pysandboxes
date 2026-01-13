import asyncio
import functools
import threading
import time
import weakref
from _weakref import ReferenceType
from asyncio import AbstractEventLoop
from contextlib import contextmanager
from typing import Optional, Any, Callable

import logging

logger = logging.getLogger(__name__)

_background_loop_ref:ReferenceType[AbstractEventLoop] = None
_server_task_ref = None
_background_thread = None

_lock = threading.Lock()
def _ensure_background_loop(new_loop:bool = False) -> Optional[AbstractEventLoop]:
    """Crée une boucle d'arrière-plan dans un thread dédié si nécessaire"""
    global _background_loop_ref, _background_thread,_lock

    if _background_loop_ref is not None:
        loop = _background_loop_ref()
        if loop is not None and loop.is_running():
            return loop
    if not new_loop:
        return None


    with _lock:
        # Double check
        logger.debug("double check")
        if _background_loop_ref is not None:
            loop = _background_loop_ref()
            if loop is not None and loop.is_running():
                return loop

        # Create a private loop in a thread
        logger.debug("Create new event")
        loop = asyncio.new_event_loop()
        loop._debug=True  # FIXME: flag pour debug
        _background_loop_ref = weakref.ref(loop)
        asyncio.set_event_loop(loop)

        start_event = threading.Event()
        def _start_background_loop() -> None:
            """Exécute la boucle événementielle en continu"""
            logger.debug("Createion de la private loop")
            asyncio.set_event_loop(loop)
            start_event.set()
            loop.run_forever()
            logger.error("Private loop stopped")

        thread = threading.Thread(
            target=_start_background_loop,
            daemon=True,
            name="Sandbox Private loop"
        )
        thread.start()
        start_event.wait()
        while not loop.is_running():
            time.sleep(0)
    return loop


def sandbox_loop(func: Callable[..., Any]) -> Callable[..., Any]:

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        old_loop = None
        try:
            old_loop = asyncio.get_event_loop()
        except RuntimeError:
            pass

        loop = get_sandbox_loop()
        asyncio.set_event_loop(loop)
        assert asyncio.get_event_loop().get_debug()

        result = func(*args, **kwargs)

        asyncio.set_event_loop(old_loop)
        return result

    return wrapper

def get_sandbox_loop() -> AbstractEventLoop:
    """Lance le serveur dans la boucle appropriée"""
    global _server_task_ref

    try:
        # # Reuse private loop?
        loop = _ensure_background_loop(new_loop=True)  # TODO: vérifer new_loop
        if loop:
            # logger.debug("Reuse the private event loop")
            return loop
        # Try to use the active loop
        loop = asyncio.get_event_loop()
        # logger.debug("Use the active loop")
        return loop
    except RuntimeError:
        # Create a private loop
        # logger.debug("Creating a private event loop")
        return _ensure_background_loop(new_loop=True) # FIXME: propablement plus possible
