from concurrent.futures import ThreadPoolExecutor

from langgraph_codeagent.BasePythonExecutor import BaseThreadPoolPythonExecutor


class PythonThreadExecutor(BaseThreadPoolPythonExecutor):
    def __init__(self,
                 max_workers=None,
                 thread_name_prefix='',
                 initargs=()):
        if not thread_name_prefix:
            thread_name_prefix = "PythonExecutor-thread"
        super().__init__(
            ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix=thread_name_prefix,
                initargs=initargs)
        )
