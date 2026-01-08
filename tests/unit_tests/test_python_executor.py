import pytest
import textwrap

from pysandboxes.executors.BasePythonExecutor import code_to_fn, capture_last_expression, \
    async_code_to_fn, async_code_to_async_fn, \
    BasePythonExecutor
from pysandboxes.executors.ikernel_executor import IKernelExecutor
from pysandboxes.executors.python_direct_executor import PythonDirectExecutor
from pysandboxes.executors.python_interpreter_executor import PythonInterpreterExecutor
from pysandboxes.executors.python_thread_executor import PythonThreadExecutor


def test_capture_last_expression():
    assert capture_last_expression("3+4") == "_ = 3 + 4"
    assert capture_last_expression("z=1") == "z = 1\n_ = None"
    assert capture_last_expression(textwrap.dedent("""
    def toto(): 
        pass
    """)) == 'def toto():\n    pass\n_ = None'


def test_code_to_fn():
    assert code_to_fn("3+4")() == 3 + 4
    assert code_to_fn("if True:\n  9+9\n3+4")() == 3 + 4

def test_async_code_to_fn():
    assert (async_code_to_fn("3+4")()) == 3 + 4
    assert async_code_to_fn("if True:\n  9+9\n3+4")() == 3 + 4

async def test_async_code_to_async_fn():
    assert (await async_code_to_async_fn("3+4")()) == 3 + 4
    assert await async_code_to_async_fn("if True:\n  9+9\n3+4")() == 3 + 4

# %% Test Thread pool
list_implementations=[
    # PythonDirectExecutor(),
    # PythonThreadExecutor(),
    # PythonInterpreterExecutor(),
    IKernelExecutor(),
]

@pytest.mark.parametrize(
    "implementation",
    list_implementations
)
def test_sync_thread_pool(implementation:BasePythonExecutor):

    assert implementation.call("3+4").result() == 3+4
    # FIXME assert implementation.call("if True:\n  9+9\n3+4").result() == 3 + 4

@pytest.mark.parametrize(
    "implementation",
    list_implementations
)
async def test_async_thread_pool(implementation):
    assert await implementation.acall("3+4") == 3+4
    assert await implementation.acall("if True:\n  9+9\n3+4") == 3 + 4

