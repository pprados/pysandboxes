"""
Manages a private, background event loop for the sandbox environment.

This module is crucial for preventing interference between the sandbox's asynchronous
operations and the main application's event loop, especially when the main
application is also asynchronous. It creates and manages an asyncio event loop
in a separate daemon thread, ensuring that sandbox tasks run in isolation.
"""

import asyncio
import functools
import logging
import threading
import weakref
from asyncio import AbstractEventLoop
from typing import Any, Callable

from _weakref import ReferenceType

logger = logging.getLogger(__name__)

# Weak reference to the background event loop to allow for garbage collection.
_background_loop_ref: ReferenceType[AbstractEventLoop] | None = None

# Thread-safe lock for creating and managing the background loop.
_lock = threading.Lock()


def set_sandbox_loop(loop: AbstractEventLoop) -> None:
    """
    Explicitly sets the event loop to be used by the sandbox.

    This allows the sandbox to use an existing event loop instead of creating
    a new one.

    Args:
        loop: The asyncio event loop to set.
    """
    global _background_loop_ref
    assert _background_loop_ref is None or _background_loop_ref() is None
    _background_loop_ref = weakref.ref(loop)


# The background thread running the event loop.
_thread: threading.Thread | None = None


def _ensure_background_loop(new_loop: bool = False) -> AbstractEventLoop | None:
    """
    Ensures that a background event loop is running.

    Checks for an existing, running loop via a weak reference. If none is found
    and `new_loop` is True, it creates a new loop, starts it in a background
    daemon thread, and stores a weak reference to it. This is a thread-safe
    operation.

    Args:
        new_loop: If True, a new loop will be created if one is not running.

    Returns:
        The running event loop, or None if no loop is running and `new_loop` is False.
    """
    global _background_loop_ref

    if _background_loop_ref is not None:
        loop = _background_loop_ref()
        if loop is not None and loop.is_running():
            return loop
    if not new_loop:
        return None

    with _lock:
        # Double-check inside the lock to prevent race conditions.
        if _background_loop_ref is not None:
            loop = _background_loop_ref()
            if loop is not None and loop.is_running():
                return loop
        try:
            # If we are already in a coroutine, reuse the running loop.
            loop = asyncio.get_running_loop()
            _background_loop_ref = weakref.ref(loop)
            return loop
        except RuntimeError:
            logger.debug("Create a private event loop for sandbox without async call")

        # Create a new loop and run it in a background thread.
        loop = asyncio.new_event_loop()
        loop.__pysandbox__ = True  # type: ignore[attr-defined]
        _background_loop_ref = weakref.ref(loop)
        asyncio.set_event_loop(loop)

        start_event = threading.Event()

        def _start_background_loop() -> None:
            """Target for the thread; runs the event loop forever."""
            try:
                asyncio.set_event_loop(loop)
                start_event.set()
                logger.debug("Start thread for sandbox event loop")
                loop.run_forever()
                logger.debug("Stop thread for sandbox event loop")
            except SystemExit as e:
                import os

                logger.error("Exit sandbox")
                os._exit(e.args[0])
            except Exception:
                import os

                logger.exception("Exception unknown in run_forever")
                os._exit(-1)

        global _thread
        _thread = threading.Thread(
            target=_start_background_loop, daemon=True, name="Sandbox Private loop"
        )
        _thread.start()
        start_event.wait()  # Wait for the loop to be running in the new thread.
    return loop


def sandbox_loop(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator to run a function within the sandbox's event loop context.

    It temporarily switches the current asyncio event loop to the sandbox's
    private loop for the duration of the decorated function's execution,
    then restores the original loop.

    Args:
        func: The function to be decorated.

    Returns:
        The wrapped function.
    """

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

        result = func(*args, **kwargs)
        if old_loop:
            asyncio.set_event_loop(old_loop)
        return result

    return wrapper


def reset_sandbox_loop() -> None:
    """
    Resets the global sandbox loop reference.

    This clears the weak reference to the loop, allowing it and its background
    thread to be garbage collected if no longer in use. The loop itself is
    stopped from another part of the code.
    """
    global _background_loop_ref
    with _lock:
        _background_loop_ref = None


def get_sandbox_loop() -> AbstractEventLoop:
    """
    Gets the sandbox event loop, creating it if it doesn't exist.

    This is the primary way to access the sandbox's private event loop.
    On the first call, it ensures the loop is created and running in its
    background thread.

    Returns:
        The sandbox's asyncio event loop.
    """
    # Ensure a private loop is running, creating one if necessary.
    loop = _ensure_background_loop(new_loop=True)
    if loop:
        return loop
    # This part should ideally not be reached if _ensure_background_loop is correct.
    # Fallback to the current running loop, though this may not be the sandbox loop.
    loop = asyncio.get_running_loop()
    return loop
