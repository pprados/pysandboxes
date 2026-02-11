import asyncio
import contextvars
import inspect
import io
import logging
import queue
import sys
from concurrent.futures import Executor
from functools import partial
from typing import Any, Dict, Optional, Callable, Union

from ..private_loop import get_sandbox_loop

logger = logging.getLogger(__name__)

TQueue = Union[queue.Queue, asyncio.Queue]


class QueueStringIO(io.StringIO):
    """
    A custom file-like object that intercepts writes, sends them to a thread-specific queue,
    and also writes to an underlying StringIO buffer.
    """

    def __init__(self,
                 type: str,
                 queue: Optional[TQueue]):
        super().__init__()
        self.type = type
        self._message_queue: Optional[TQueue] = queue
        self._buffer: io.StringIO = io.StringIO()  # Underlying buffer for aggregated content

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
        # No-op for StringIO, but good practice for file-like objects
        self._buffer.flush()


class WrapperIO(io.TextIOBase):
    def __init__(self,
                 context: contextvars.ContextVar):
        self._context = context
        self._old = None

    def set_context(self, new_textio: io.TextIOBase):
        if not self._old:
            self._old = self._context.get()
            self._context.set(new_textio)
            assert not isinstance(self._old, WrapperIO)

    def __getattr__(self, name: str) -> Any:
        # Called only if attribute not found the usual way
        if name in ("write", "flush", "_context", "_old"):
            return super().__getattr__(name)
        return getattr(self._old, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in ("write", "flush", "_context", "_old"):
            # Assign _target to self, not to target
            super().__setattr__(name, value)
        else:
            setattr(self._old, name, value)

    def __del__(self):
        if self._old:
            self._context.set(self._old)

    def write(self, s: str) -> int:
        return self._context.get().write(s)

    def flush(self) -> None:
        self._context.get().flush()


sys.stdout = WrapperIO(contextvars.ContextVar(
    'current_stdout', default=sys.stdout))
sys.stderr = WrapperIO(contextvars.ContextVar(
    'current_stderr', default=sys.stderr))


def catch_stdio(
        queue: Optional[TQueue],
        fn: Callable,
        kwargs: Dict[str, Any],
        *args: Any,
) -> Dict[str, Any]:
    assert asyncio.get_event_loop() == get_sandbox_loop(), "Should be in sandbox loop"
    result = asyncio.run_coroutine_threadsafe(
        acatch_stdio(queue, fn, kwargs, *args),
        asyncio.get_event_loop()
    )
    return result.result()


async def acatch_stdio(
        queue: Optional[TQueue],
        fn: Callable,
        kwargs: Dict[str, Any],
        *args: Any,
) -> Dict[str, Any]:
    assert asyncio.get_event_loop() == get_sandbox_loop(), "Should be in sandbox loop"
    captured_stdout: io.StringIO = QueueStringIO(type="stdout", queue=queue)
    captured_stderr: io.StringIO = QueueStringIO(type="stderr", queue=queue)
    fn_result: Any = None

    async def run_in_context() -> Dict[str, Any]:
        logger.debug("async run_in_context()...")
        # Allows modification of eval_result from outer scope
        nonlocal fn_result
        # Set the context variables for the current context
        sys.stdout.set_context(captured_stdout)
        sys.stderr.set_context(captured_stderr)
        result: Dict[str, Any]

        try:
            use_async = inspect.iscoroutinefunction(fn)

            if use_async:
                fn_result = await fn(*args, **kwargs)
            else:
                fn_result = fn(*args, **kwargs)
            result = {"result": fn_result}
            if queue:
                if isinstance(queue, asyncio.Queue):
                    queue.put_nowait(result)
                else:
                    queue.put(result)
            return result
        except Exception as e:
            import tblib

            result = {
                "exception": (e, tblib.Traceback(e.__traceback__))
            }

            if isinstance(queue, asyncio.Queue):
                queue.put_nowait(result)
            else:
                queue.put(result)
            return result

    result = await run_in_context()
    result["stdout"] = captured_stdout.getvalue()
    result["stderr"] = captured_stderr.getvalue()

    return result


def _thread_catch_stream(
        fn: Callable,
        code_string: str,
        *,
        globals_dict: dict = None,
        locals_dict: dict = None,
        executor: Executor
) -> None:
    stream_queue = queue.Queue()
    fut = executor.submit(fn,
                          code_string,
                          globals_dict=globals_dict,
                          locals_dict=locals_dict,
                          queue=stream_queue,
                          )
    while stream_queue:
        msg = stream_queue.get()

        if "result" in msg:
            break
        elif "exception" in msg:
            break
        elif "stdout" in msg:
            print(msg["stdout"])
        elif "stderr" in msg:
            print(msg["stderr"], file=sys.stderr, flush=True)
    result = fut.result()
    if "result" in result:
        return result["result"]
    elif "exception" in result:
        raise result["exception"]


eval_stream = partial(catch_stdio, eval)
exec_stream = partial(catch_stdio, exec)
thread_eval_stream = partial(_thread_catch_stream, eval_stream)
thread_exec_stream = partial(_thread_catch_stream, exec_stream)
