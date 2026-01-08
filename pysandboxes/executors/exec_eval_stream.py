import contextvars
import io
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, Executor
from functools import partial
import asyncio
import queue
from typing import Any, Dict, Optional, Callable, Union

logger = logging.getLogger(__name__)

# TODO: put_nowait
class QueueStringIO(io.StringIO):
    """
    A custom file-like object that intercepts writes, sends them to a thread-specific queue,
    and also writes to an underlying StringIO buffer.
    """

    def __init__(self,
                 type: str,
                 queue: Optional[Union[queue.Queue,asyncio.Queue]]):
        super().__init__()
        self.type = type
        self._message_queue: Optional[Union[queue.Queue,asyncio.Queue]] = queue
        self._buffer: io.StringIO = io.StringIO()  # Underlying buffer for aggregated content

    def write(self, s: str) -> int:
        """
        Intercepts the write operation. Adds the content to the message queue
        and then writes to the internal buffer.
        """
        # Put the message in the queue, associated with the thread ID
        if self._message_queue:
            if isinstance(asyncio.Queue):
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


def _catch_stream(
        fn: Callable,
        code_string: str,
        # *,
        globals_dict: Dict[str, Any] = None,
        locals_dict: Dict[str, Any] = None,
        queue: Optional[queue.Queue] = None,
) -> Dict[str, Any]:
    if globals_dict is None:
        globals_dict = {}
    if locals_dict is None:
        locals_dict = {}

    captured_stdout: io.StringIO = QueueStringIO(type="stdout", queue=queue)
    captured_stderr: io.StringIO = QueueStringIO(type="stderr", queue=queue)
    eval_result: Any = None

    # Create a new context for this operation
    # This ensures that contextvars changes are isolated to this specific call
    # and not visible to other parts of the thread that are not within this context.
    # This is particularly important for asynchronous code, but good practice here too.
    ctx = contextvars.copy_context()

    def run_in_context():
        # Allows modification of eval_result from outer scope
        nonlocal eval_result
        # Set the context variables for the current context
        sys.stdout.set_context(captured_stdout)
        sys.stderr.set_context(captured_stderr)

        try:
            logger.error(f"Running code: {code_string}")  # FIXME
            eval_result = fn(code_string, globals_dict, locals_dict)
            result = {"result": eval_result}
            if queue:
                queue.put(result)
            return result
        except Exception as e:
            # If an error occurs during eval, print it to stderr
            result = {"exception": e}
            if queue:
                print(f"PUT exception")
                queue.put(result)
            return result

    # Run the function within the new context.
    # The contextvars are automatically restored after this call.
    result: Dict[str, Any] = ctx.run(run_in_context)
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
            eval_result = msg["result"]
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


eval_stream = partial(_catch_stream, eval)
exec_stream = partial(_catch_stream, exec)
thread_eval_stream = partial(_thread_catch_stream, eval_stream)
thread_exec_stream = partial(_thread_catch_stream, exec_stream)
