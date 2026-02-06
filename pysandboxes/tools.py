import asyncio
import contextvars
import inspect
import os
import re
import sys
from typing import Optional, Union, Callable, Awaitable, Any, Tuple, List, \
    Iterator

from .sb_types import ConfigLines, ConfigLine, Envs


def substitute_config_env_vars(lines: ConfigLines, env_vars: Envs) -> ConfigLines:
    """
    The function supports two substitution formats:
    1. ${VAR_NAME}: Replaces the placeholder with the value of VAR_NAME from
       the env_vars dictionary. If the variable is not found, it's replaced
       with an empty string.
    2. ${VAR_NAME:-default_value}: Replaces the placeholder with the value of
       VAR_NAME if it exists in env_vars. Otherwise, it uses the provided
       default_value.

    """
    # This regular expression is designed to find all occurrences of the
    # ${...} pattern.
    # - Group 1 ([a-zA-Z0-9_]+): Captures the variable name. It consists of
    #   one or more alphanumeric characters or underscores.
    # - Group 2 (?:=...): Is an optional non-capturing group for the default value.
    # - Group 3 (.*?): Captures the default value itself, if present.
    #   The '?' makes the default value group optional.
    pattern = re.compile(r"\$\{([a-zA-Z0-9_]+)(?::=(.*?))?\}")

    def substitute(match: re.Match) -> str:
        """
        This nested function is called by re.sub for each match found.
        It performs the actual replacement logic.
        """
        var_name = match.group(1)
        default_value = match.group(2)  # This will be None if no default is provided

        # Use the variable from env_vars if it exists.
        # Otherwise, use the captured default_value.
        # If default_value is also None (the :- part was absent),
        # this expression results in an empty string.
        return env_vars.get(var_name,
                            default_value if default_value is not None else "")

    return [ConfigLine(pattern.sub(substitute, line), path, ln) for line, path, ln in
            lines]


def substitute_env_vars(lines: List[str], env_vars: Envs) -> List[str]:
    pattern = re.compile(r"\$\{([a-zA-Z0-9_]+)(?::=(.*?))?\}")

    def substitute(match: re.Match) -> str:
        var_name = match.group(1)
        default_value = match.group(2)  # This will be None if no default is provided
        return env_vars.get(var_name,
                            default_value if default_value is not None else "")

    return [pattern.sub(substitute, line) for line in lines]


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
    result: ConfigLines = []
    in_quotes: bool = False
    quote_char: Optional[str] = None
    i: int = 0

    while i < len(line):
        char: str = line[i]

        # Handle quotes (single or double)
        if char in ['"', "'"] and not in_quotes:
            in_quotes = True
            quote_char = char
            result.append(char)
        elif char == quote_char and in_quotes:
            # Check if the quote is escaped
            if i > 0 and line[i - 1] == '\\':
                result.append(char)
            else:
                in_quotes = False
                quote_char = None
                result.append(char)
        # If we find a # and we're not inside quotes
        elif char == '#' and not in_quotes:
            # Stop here, this is the start of the comment
            break
        else:
            result.append(char)

        i += 1

    # Remove trailing whitespace
    return ''.join(result).rstrip()


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
    def _is_interactive():
        """Decide whether this is running in a REPL or IPython notebook"""
        if hasattr(sys, "ps1") or hasattr(sys, "ps2"):
            return True
        try:
            main = __import__("__main__", None, None, fromlist=["__file__"])
        except ModuleNotFoundError:
            return False
        return not hasattr(main, "__file__")

    def _is_debugger():
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
_is_in_sandbox = False

_sandboxed = contextvars.ContextVar(
    'sanboxed', default=False)


def is_in_sandbox() -> bool:
    return _sandboxed.get()


def set_is_in_sandbox(value: bool) -> None:
    _sandboxed.set(value)


SyncOrAsyncFunc = Union[
    Callable[[], None],  # Fonction synchrone
    Callable[[], Awaitable[None]]  # Fonction asynchrone
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
    if hasattr(func, '__qualname__'):
        callable_name = func.__qualname__
    elif hasattr(func, '__name__'):
        callable_name = func.__name__
    elif inspect.ismethod(func):
        # For bound methods, func.__func__ gives the underlying function
        if hasattr(func.__func__, '__qualname__'):
            callable_name = func.__func__.__qualname__
        elif hasattr(func.__func__, '__name__'):
            callable_name = func.__func__.__name__
    elif isinstance(func, type):  # It's a class
        callable_name = func.__qualname__
    elif hasattr(func, '__class__') and hasattr(func.__class__, '__call__'):
        # It's an instance of a class with a __call__ method
        callable_name = func.__class__.__qualname__
        if callable_name:
            callable_name += ".__call__"
    return module_name, callable_name


mixed_sync_and_async_error = (
    "It's impossible to mixte synchronize and asynchronize sandbox function.")


def check_mixte_async_async():
    try:
        if asyncio.get_running_loop():
            raise RuntimeError(mixed_sync_and_async_error)
    except RuntimeError as e:
        if str(e) == "no running event loop":
            pass  # Ignore
        else:
            raise
