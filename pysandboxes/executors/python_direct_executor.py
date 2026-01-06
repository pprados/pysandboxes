import concurrent
from concurrent.futures import Executor

from pysandboxes.BasePythonExecutor import BaseThreadPoolPythonExecutor


class DirectExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        fut = concurrent.futures.Future()
        fut.set_result(fn(*args,**kwargs))
        return fut


class PythonDirectExecutor(BaseThreadPoolPythonExecutor):
    def __init__(self):
        super().__init__(
            DirectExecutor()
        )
