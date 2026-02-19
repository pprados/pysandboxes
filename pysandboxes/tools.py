import asyncio
import contextvars
import inspect
import os
import re
import sys
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Union, Mapping,
)

from .sb_types import ConfigLine, ConfigLines

Environ = Mapping[str, str] | os._Environ


def resolve_env_variables(s: str, envs: Environ) -> str:
    # Motif pour capturer les expressions ${VAR} ou ${VAR:=default}
    pattern = re.compile(r"\$\{([^{}:=]+)(?::=([^{}]*))?\}")

    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default_value = match.group(2)

        while "${" in var_name:
            var_name = resolve_env_variables(var_name, envs)

        value = envs.get(var_name, default_value)
        return value

    while re.search(r"\${.*}", s):
        s = pattern.sub(replace, s)
    return s


def substitute_env_vars(lines: List[str],
                        env_vars: Environ
                        ) -> List[str]:
    return [resolve_env_variables(line, env_vars) for line in lines]


def substitute_config_env_vars(lines: ConfigLines,
                               env_vars: Environ) -> ConfigLines:
    return [
        ConfigLine(resolve_env_variables(line, env_vars), path, ln)
        for line, path, ln in lines
    ]


def remove_config_comments(config: ConfigLines) -> ConfigLines:
    processed_lines: ConfigLines = []

    for line, path, ln in config:
        # Remove end-of-line comments while respecting quotes
        cleaned_line: str = _remove_comment(line.strip())
        if cleaned_line.startswith("{"):
            # Remove template lines
            continue
        # Filter out empty lines and lines that are full comments
        if cleaned_line and not cleaned_line.lstrip().startswith("#"):
            processed_lines.append(ConfigLine(cleaned_line, path, ln))

    return processed_lines


def remove_comments(config: List[str]) -> List[str]:
    processed_lines: List[str] = []

    for line in config:
        # Remove end-of-line comments while respecting quotes
        cleaned_line: str = _remove_comment(line.strip())

        # Filter out empty lines and lines that are full comments
        if cleaned_line and not cleaned_line.lstrip().startswith("#"):
            processed_lines.append(cleaned_line)

    return processed_lines


def _remove_comment(line: str) -> str:
    """
    Removes comments from a line while respecting quotes.

    Args:
        line: The line to process

    Returns:
        Line without comment
    """
    result: List[str] = []
    in_quotes: bool = False
    quote_char: Optional[str] = None
    i: int = 0

    while i < len(line):
        ch: str = line[i]

        # Handle quotes (single or double)
        if ch in ['"', "'"] and not in_quotes:
            in_quotes = True
            quote_char = ch
            result.append(ch)
        elif ch == quote_char and in_quotes:
            # Check if the quote is escaped
            if i > 0 and line[i - 1] == "\\":
                result.append(ch)
            else:
                in_quotes = False
                quote_char = None
                result.append(ch)
        # If we find a # and we're not inside quotes
        elif ch == "#" and not in_quotes:
            # Stop here, this is the _start of the comment
            break
        else:
            result.append(ch)

        i += 1

    # Remove trailing whitespace
    return "".join(result).rstrip()


def _walk_to_base(path: str, base: str) -> Iterator[str]:
    """
    Yield directories starting from the given directory up to the root
    """
    if not os.path.exists(path):
        raise IOError("Starting path not found")

    if os.path.isfile(path):
        path = os.path.dirname(path)

    last_dir = None
    current_dir = os.path.abspath(path)
    while last_dir != current_dir:
        yield current_dir
        if current_dir == base:
            break
        parent_dir = os.path.abspath(os.path.join(current_dir, os.path.pardir))
        last_dir, current_dir = current_dir, parent_dir


def find_config(
        filename: str,
        raise_error_if_not_found: bool = False,
        usecwd: bool = False,
) -> str:
    """
    Search in increasingly higher folders for the given file

    Returns path to the file if found, or an empty string otherwise
    """

    # TODO: search in module of the caller
    def _is_interactive() -> bool:
        """Decide whether this is running in a REPL or IPython notebook"""
        if hasattr(sys, "ps1") or hasattr(sys, "ps2"):
            return True
        try:
            main = __import__("__main__", None, None, fromlist=["__file__"])
        except ModuleNotFoundError:
            return False
        return not hasattr(main, "__file__")

    def _is_debugger() -> bool:
        return sys.gettrace() is not None

    if usecwd or _is_interactive() or _is_debugger() or getattr(sys, "frozen", False):
        # Should work without __file__, e.g. in REPL or IPython notebook.
        path = os.getcwd()
    else:
        # will work for .py files
        frame = sys._getframe()
        current_file = __file__

        while frame.f_code.co_filename == current_file or not os.path.exists(
                frame.f_code.co_filename
        ):
            assert frame.f_back is not None
            frame = frame.f_back
        frame_filename = frame.f_code.co_filename
        path = os.path.dirname(os.path.abspath(frame_filename))

    for dirname in _walk_to_base(path, os.getcwd()):
        check_path = os.path.join(dirname, filename)
        if os.path.isfile(check_path):
            return check_path

    if raise_error_if_not_found:
        raise IOError("File not found")

    return ""


# %% -----------------------

_sandboxed = contextvars.ContextVar("sanboxed", default=0)
_is_in_sandbox: int = 0


def is_in_sandbox() -> bool:
    global _is_in_sandbox
    return _sandboxed.get() > 0
    # return _is_in_sandbox > 0


def set_is_in_sandbox(value: bool) -> None:
    global _is_in_sandbox
    if value:
        _sandboxed.set(_sandboxed.get() + 1)
        # _is_in_sandbox += 1
    else:
        _sandboxed.set(_sandboxed.get() - 1)
        assert _sandboxed.get() >= 0
        # _is_in_sandbox -= 1


SyncOrAsyncFunc = Union[
    Callable[[], None],  # Fonction synchrone
    Callable[[], Awaitable[None]],  # Fonction asynchrone
]


def get_callable_info(func: Callable[..., Any]) -> Tuple[Optional[str], Optional[str]]:
    """
    Retrieves the module name and the fully qualified name of a callable.

    Args:
        func: The callable object (function, method, class method, static method,
              lambda, or callable instance).

    Returns:
        A tuple containing:
        - The name of the module where the callable is defined (str or None).
        - The fully qualified name of the callable (str or None).
    """
    module_name: Optional[str] = None
    callable_name: Optional[str] = None

    # Get the module name using inspect.getmodule()
    # This works well for functions, methods, and class methods
    module_obj = inspect.getmodule(func)
    if module_obj:
        module_name = module_obj.__name__

    # Get the qualified name of the callable
    # __qualname__ provides the dotted path from the module to the callable,
    # useful for nested functions or methods within classes.
    # __name__ provides just the simple name.
    if hasattr(func, "__qualname__"):
        callable_name = func.__qualname__
    elif hasattr(func, "__name__"):
        callable_name = func.__name__
    elif inspect.ismethod(func):
        # For bound methods, func.__func__ gives the underlying function
        if hasattr(func.__func__, "__qualname__"):
            callable_name = func.__func__.__qualname__
        elif hasattr(func.__func__, "__name__"):
            callable_name = func.__func__.__name__
    elif isinstance(func, type):  # It's a class
        callable_name = func.__qualname__
    elif hasattr(func, "__class__") and hasattr(func.__class__, "__call__"):
        # It's an instance of a class with a __call__ method
        callable_name = func.__class__.__qualname__
        if callable_name:
            callable_name += ".__call__"
    return module_name, callable_name


mixed_sync_and_async_error = (
    "It's impossible to mix synchronous and asynchronous sandbox functions. "
    "Only use annotated asynchronous functions with an asynchronous sandbox."
)


def check_mixte_async_async() -> None:
    try:
        if asyncio.get_running_loop():
            raise RuntimeError(mixed_sync_and_async_error)
    except RuntimeError as e:
        if str(e) == "no running event loop":
            pass  # Ignore
        else:
            raise


def follow_links_executable(executable: Path, all_paths: Set[Path]) -> None:
    if executable.parents[0].name == "bin":
        if str(executable.parent.parent) not in all_paths:
            all_paths.add(executable.parent.parent)
        else:
            return
    else:
        if executable not in all_paths:
            all_paths.add(executable)
        else:
            return
    if executable.is_symlink():
        try:
            follow_links_executable(executable.resolve(strict=True), all_paths)
        except FileNotFoundError:
            raise RuntimeError(
                "Impossible to resolve the sys.executable `%s`", sys.executable
            )
