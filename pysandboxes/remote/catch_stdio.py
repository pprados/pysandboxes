"""
This module provides utilities for capturing stdout and stderr streams,
especially in a multi-threaded or asynchronous context.
It uses context variables to manage thread-specific output streams.
"""

import asyncio
import contextvars
import inspect
import io
import logging
import queue
import sys
from typing import Any, Callable

from ..private_loop import get_sandbox_loop

logger = logging.getLogger(__name__)

TQueue = queue.Queue | asyncio.Queue


class QueueStringIO(io.StringIO):
    """
    A custom file-like object that intercepts writes, sends them to a
    thread-specific queue, and also writes to an underlying StringIO buffer.
    """

    def __init__(self, type: str, queue: TQueue | None):
        """
        Initializes the QueueStringIO.

        Args:
            type: The type of stream ("stdout" or "stderr").
            queue: The queue to which messages will be sent.
        """
        super().__init__()
        self.type = type
        self._message_queue: TQueue | None = queue
        self._buffer: io.StringIO = (
            io.StringIO()
        )  # Underlying buffer for aggregated content

    def write(self, s: str) -> int:
        """
        Intercepts the write operation. Adds the content to the message queue
        and then writes to the internal buffer.
        """
        # Put the message in the queue, associated with the thread ID
        if self._message_queue:
            if isinstance(self._message_queue, asyncio.Queue):
                self._message_queue.put_nowait({self.type: s})
            else:
                self._message_queue.put({self.type: s})
        # Write to the underlying buffer to capture the full output
        return self._buffer.write(s)

    def getvalue(self) -> str:
        """
        Returns the full captured content from the underlying buffer.
        """
        return self._buffer.getvalue()

    def flush(self) -> None:
        """Flushes the underlying buffer."""
        # No-op for StringIO, but good practice for file-like objects
        self._buffer.flush()


class WrapperIO(io.TextIOBase):
    """
    A wrapper for sys.stdout/sys.stderr to allow for context-local redirection.
    It uses a context variable to hold the current output stream.
    """

    def __init__(self, context: contextvars.ContextVar) -> None:
        """
        Initializes the WrapperIO.

        Args:
            context: The context variable that holds the current stream.
        """
        self._context = context
        self._old: contextvars.ContextVar | None = None

    def set_context(self, new_textio: io.TextIOBase) -> None:
        """
        Sets a new stream for the current context.

        Args:
            new_textio: The new stream to be used for the current context.
        """
        if not self._old:
            self._old = self._context.get()
            self._context.set(new_textio)
            assert not isinstance(self._old, WrapperIO)

    def __getattr__(self, name: str) -> Any:
        # Called only if attribute not found the usual way
        if name in ("write", "flush", "_context", "_old"):
            return super().__getattr__(name)  # type: ignore[misc]
        return getattr(self._old, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("write", "flush", "_context", "_old"):
            # Assign _target to self, not to target
            super().__setattr__(name, value)
        else:
            setattr(self._old, name, value)

    def __del__(self) -> None:
        """Restores the original stream when the wrapper is deleted."""
        if self._old:
            self._context.set(self._old)

    def write(self, s: str) -> int:
        """
        Writes to the stream of the current context.

        Args:
            s: The string to write.

        Returns:
            The number of characters written.
        """
        return self._context.get().write(s)

    def flush(self) -> None:
        """Flushes the stream of the current context."""
        self._context.get().flush()


sys.stdout = WrapperIO(contextvars.ContextVar("current_stdout", default=sys.stdout))
sys.stderr = WrapperIO(contextvars.ContextVar("current_stderr", default=sys.stderr))


def catch_stdio(
    queue: TQueue | None,
    fn: Callable,
    kwargs: dict[str, Any],
    *args: Any,
) -> dict[str, Any]:
    """
    Catches stdout and stderr for a synchronous function running in the sandbox loop.

    Args:
        queue: The queue to which output and results will be sent.
        fn: The synchronous function to execute.
        kwargs: Keyword arguments for the function.
        *args: Positional arguments for the function.

    Returns:
        A dictionary containing the result, stdout, and stderr.
    """
    assert asyncio.get_event_loop() == get_sandbox_loop(), "Should be in sandbox loop"
    result = asyncio.run_coroutine_threadsafe(
        acatch_stdio(queue, fn, kwargs, *args), asyncio.get_event_loop()
    )
    return result.result()


async def acatch_stdio(
    sync_or_async_queue: TQueue | None,
    fn: Callable,
    kwargs: dict[str, Any],
    *args: Any,
) -> dict[str, Any]:
    """
    Asynchronously catches stdout and stderr for a function (sync or async).

    This function sets up context-local streams to capture the output of the
    given function.

    Args:
        sync_or_async_queue: The queue (sync or async) to send output to.
        fn: The function to execute.
        kwargs: Keyword arguments for the function.
        *args: Positional arguments for the function.

    Returns:
        A dictionary containing the result, stdout, and stderr.
    """
    assert asyncio.get_event_loop() == get_sandbox_loop(), "Should be in sandbox loop"
    captured_stdout: io.StringIO = QueueStringIO(
        type="stdout", queue=sync_or_async_queue
    )
    captured_stderr: io.StringIO = QueueStringIO(
        type="stderr", queue=sync_or_async_queue
    )
    fn_result: Any = None

    async def run_in_context() -> dict[str, Any]:
        """
        Runs the function in a context with captured stdio.
        Handles both sync and async functions and captures exceptions.
        """
        logger.debug("async run_in_context()...")
        # Allows modification of eval_result from outer scope
        nonlocal fn_result
        # Set the context variables for the current context
        sys.stdout.set_context(captured_stdout)  # type: ignore[union-attr]
        sys.stderr.set_context(captured_stderr)  # type: ignore[union-attr]
        result: dict[str, Any]

        try:
            use_async = inspect.iscoroutinefunction(fn)

            if use_async:
                fn_result = await fn(*args, **kwargs)
            else:
                fn_result = fn(*args, **kwargs)
            result = {"result": fn_result}
            if sync_or_async_queue is not None:
                if isinstance(sync_or_async_queue, asyncio.Queue):
                    sync_or_async_queue.put_nowait(result)
                elif isinstance(sync_or_async_queue, queue.Queue):
                    sync_or_async_queue.put(result)
        except Exception as e:
            import tblib

            result = {"exception": (e, tblib.Traceback(e.__traceback__))}

            if sync_or_async_queue is not None:
                if isinstance(sync_or_async_queue, asyncio.Queue):
                    sync_or_async_queue.put_nowait(result)
                elif isinstance(sync_or_async_queue, queue.Queue):
                    sync_or_async_queue.put(result)
        return result

    async def run() -> dict[str, Any]:
        try:
            use_async = inspect.iscoroutinefunction(fn)

            if use_async:
                fn_result = await fn(*args, **kwargs)
            else:
                fn_result = fn(*args, **kwargs)
            result = {"result": fn_result}
        except Exception as e:
            import tblib

            result = {"exception": (e, tblib.Traceback(e.__traceback__))}
        return result

    result = await run_in_context()
    # result = await run()
    result["stdout"] = captured_stdout.getvalue()
    result["stderr"] = captured_stderr.getvalue()

    return result
