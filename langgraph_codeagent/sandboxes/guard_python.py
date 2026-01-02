import ast
import asyncio
import io
import textwrap
import warnings
from contextlib import redirect_stdout
from random import choice
from string import ascii_uppercase
from typing import Callable, Any, Optional

from RestrictedPython import RestrictingNodeTransformer, safe_builtins, utility_builtins
from RestrictedPython.PrintCollector import PrintCollector
from RestrictedPython.transformer import copy_locations
from final_answer import final_answer
from langgraph_codeagent.BasePythonExecutor import BasePythonExecutor

try:
    from concurrent.futures import InterpreterPoolExecutor as PoolExecutor
except (ModuleNotFoundError, ImportError):
    try:
        from interpreters_backport.concurrent.futures import \
            InterpreterPoolExecutor as PoolExecutor
    except ModuleNotFoundError:
        from concurrent.futures import ThreadPoolExecutor as PoolExecutor

        warnings.warn("Use classical PoolExecutor")
# FIXME: la version interpreters_backport ne semble pas fonctionner.
from concurrent.futures import ThreadPoolExecutor as PoolExecutor

_threadpool = PoolExecutor(max_workers=100)


USE_APPLY = False  # FIXME

# On peut vérifier les invocations pour ne garder que les invocations des tools ?
if USE_APPLY:
    def guard_apply(func, *args, **kwargs):
        print(f"***Track apply {func=},{args=},{kwargs=}")
        return func(*args, **kwargs)


def run_in_guarded_python(code_action: str,
                          tools: Optional[dict[str, Callable]]=None) -> str:
    from RestrictedPython import compile_restricted

    # rand_str = ''.join(choice(ascii_uppercase) for i in range(10))

    # def guarded_import(name: str, globals: dict, locals: dict, fromlist: list[str],
    #                    level: int) -> Any:
    #     # print(f"***Track import {name=},{fromlist=},{level=}")
    #     if name.startswith(_GUARD_IMPORT_MARKER):
    #         name = name[len(_GUARD_IMPORT_MARKER):]
    #     else:
    #         return None
    #     return __builtins__.__import__(name, globals, locals, fromlist, level)

    class LangGraphPolicy(RestrictingNodeTransformer):
        # def check_import_names(self, node):
        #     """Check the names being imported.
        #
        #     This is a protection against rebinding dunder names like
        #     _getitem_, _write_ via imports.
        #
        #     => 'from _a import x' is ok, because '_a' is not added to the scope.
        #     """
        #     for name in node.names:
        #         if '*' in name.name:
        #             self.error(node, '"*" imports are not allowed.')
        #         if name.asname:
        #             self.check_name(node, name.asname)
        #
        #     return self.node_contents_visit(node)

        def visit_Call(self, node):
            if not USE_APPLY:
                return super().visit_Call(node)
            if isinstance(node.func, ast.Name):
                if node.func.id == 'exec':
                    self.error(node, 'Exec calls are not allowed.')
                elif node.func.id == 'eval':
                    self.error(node, 'Eval calls are not allowed.')

            needs_wrap = False

            needs_wrap = True

            for keyword_arg in node.keywords:
                if keyword_arg.arg is None:
                    needs_wrap = True

            node = self.node_contents_visit(node)

            if not needs_wrap:
                return node

            node.args.insert(0, node.func)
            node.func = ast.Name('_apply_', ast.Load())
            copy_locations(node.func, node.args[0])
            return node

    loc = {}  # TODO: utiliser loc pour les tools
    encapsuled_code = f"""
{code_action}
"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        byte_code = compile_restricted(encapsuled_code,
                                       '<inline>',
                                       'exec',
                                       policy=LangGraphPolicy)

        print_collector = PrintCollector
        safe_agent_builtins = {
            '__builtins__': (
                    safe_builtins |
                    utility_builtins |
                    {"__import__": __import__} |
                    # {"__import__": guarded_import}
                    {}
                    ),
            "_print_": print_collector,
        }
        if USE_APPLY:
            safe_agent_builtins["_apply_"] = guard_apply

        f = io.StringIO()
        with redirect_stdout(f):
            exec(byte_code, safe_agent_builtins, loc)
    return f.getvalue()


# %%

# class RestrictedPythonExecutor(BasePythonExecutor):
#     """
#     Offers an implementation using AST manipulation to limit the capabilities of the
#     generated code. The code must directly invoke the tools as functions.
#     """
#
#     # Execute le code qui invoque directement les tools, en synchrone.
#     # Cela dans un thread dédié, si possible via un autre interpreteur pour l'isolation.
#     def call(self,
#              code_action: str,
#              tools: Optional[dict[str, Callable]]=None,
#              timeout: Optional[int] = None) -> tuple[Any, str, bool]:
#         # TODO: voir comment capturer avec final_answer
#         # Version directe
#         # return run_in_guarded_python(code_action, tools)
#
#         # Version via le pool de thread
#         return (_threadpool.submit(run_in_guarded_python, code_action, tools)
#                 .result(timeout=timeout))
#
#     async def acall(self,
#                     code_action: str,
#                     tools: Optional[dict[str, Callable]] = None,
#                     timeout: Optional[int] = None) -> tuple[Any, str, bool]:
#         loop = asyncio.get_event_loop()
#         future = loop.run_in_executor(_threadpool, run_in_guarded_python,
#                                       code_action,
#                                       tools)
#         await asyncio.wait_for(future, timeout=timeout)
