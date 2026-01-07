from concurrent.futures import ThreadPoolExecutor

try:
    from concurrent.futures import InterpreterPoolExecutor
except ImportError:
    from interpreters_backport.concurrent.futures import InterpreterPoolExecutor

from .BasePythonExecutor import BaseThreadPoolPythonExecutor

# TODO:
# Force le config, pour interdire les sous-threads !
# config = _interpreters.new_config("isolated", allow_threads=False)
# id=_interpreters.create(config)
# FIXME Il semble que cela ne fonctionne pas, car il n'invoque pas _interpqueues en python 3.14
# TODO: ca fonctionne, mais pas dans __main__.
# Il y a un interpreter par PythonInterpreterExecutor
# TODO: a confirmer
class PythonInterpreterExecutor(BaseThreadPoolPythonExecutor):
    def __init__(self,
                 max_workers=None,
                 thread_name_prefix='',
                 initargs=()):
        if not thread_name_prefix:
            thread_name_prefix = "PythonExecutor-interpreter"
        super().__init__(
            InterpreterPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix=thread_name_prefix,
                initargs=initargs,
                shared=None
            )
        )
