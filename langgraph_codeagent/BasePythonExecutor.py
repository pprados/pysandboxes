from concurrent.futures import ThreadPoolExecutor, Executor

import asyncio
import textwrap
from abc import abstractmethod
from random import choice
from string import ascii_uppercase
from typing import Any, Callable, Optional, Awaitable

wrapper_function_name = "__wrapper__"

import ast

import ast

import ast

def capture_last_expression(source: str) -> str:
    """
    Transforms Python source code to assign the result of the last expression
    to the variable '_', similar to how IPython does it.

    Parameters:
        source (str): Python code as a string

    Returns:
        str: Modified source code as a string
    """
    # Parse the source into an AST
    tree = ast.parse(source, mode="exec")

    # Do nothing if the code is empty
    if not tree.body:
        return source

    # Check if the last statement is a bare expression (e.g., `x + 1`)
    last_stmt = tree.body[-1]
    if isinstance(last_stmt, ast.Expr):
        # Replace the last expression with an assignment to "_"
        assignment = ast.Assign(
            targets=[ast.Name(id="_", ctx=ast.Store())],
            value=last_stmt.value,
            lineno=last_stmt.lineno,
            end_lineno=last_stmt.end_lineno,

        )
        tree.body[-1] = assignment
    else:
        assignment = ast.Assign(
            targets=[ast.Name(id="_", ctx=ast.Store())],
            lineno=last_stmt.lineno+1,
            end_lineno=last_stmt.end_lineno+1,
            value=ast.Constant(
                kind=type(None),
                value=None
            )
        )
        tree.body.append(assignment)


    # Convert the modified AST back to source code
    return ast.unparse(tree)

def _code_indent(code: str,prefix:str) -> str:
    lines = code.split("\n")
    return "\n".join([prefix+line for line in lines])

def code_to_fn(code_action: str) -> Callable:
    encapsuled_code = f"""
def {wrapper_function_name}():
{_code_indent(capture_last_expression(code_action), prefix="  ")}
  return _
"""
    loc = {}
    exec(encapsuled_code, {}, loc)
    return loc[wrapper_function_name]


def async_code_to_fn(code_action: str) -> Awaitable[Any]:
    encapsuled_code = f"""
def {wrapper_function_name}():
  async def __inner_wrapper__():
{_code_indent(capture_last_expression(code_action), "    ")}
    return _
  import asyncio
  return asyncio.run(__inner_wrapper__())
"""
    loc = {}
    exec(encapsuled_code, {}, loc)
    return loc[wrapper_function_name]


def async_code_to_async_fn(code_action: str) -> Awaitable[Any]:
    encapsuled_code = f"""
async def {wrapper_function_name}():
{_code_indent(capture_last_expression(code_action), "  ")}
  return _
"""  # FIXME: return direct sans le _
    loc = {}
    exec(encapsuled_code, {}, loc)
    return loc[wrapper_function_name]


class BasePythonExecutor:
    # TODO: capture des stdout
    @abstractmethod
    def call(self,
             code_action: str,
             tools: Optional[dict[str, Callable]]=None,
             timeout: Optional[int] = None) -> Any:
        pass

    @abstractmethod
    async def acall(self,
                    code_action: str,
                    tools: Optional[dict[str, Callable]]=None,
                    timeout: Optional[int] = None) -> Awaitable[Any]:
        pass


class BaseThreadPoolPythonExecutor(BasePythonExecutor):
    def __init__(self, executor: Executor):
        self._executor = executor

    def __del__(self):
        self._executor.shutdown()

    def call(self,
             code_action: str,
             tools: Optional[dict[str, Callable]]=None,
             timeout: Optional[int] = None) -> Any:

        future_result = self._executor.submit(code_to_fn(code_action))
        try:
            return future_result.result(timeout=timeout)
        except TimeoutError:
            # TODO: cancel du job ?
            raise

    async def acall(self,
                    code_action: str,
                    tools: Optional[dict[str, Callable]]=None,
                    timeout: Optional[int] = None) -> Awaitable[Any]:
        return await async_code_to_async_fn(code_action)()
