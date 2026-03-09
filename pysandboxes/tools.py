# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Utility functions for PySandboxes.

This module provides common utility functions used throughout the PySandboxes
framework, including environment variable resolution, configuration processing,
function type checking, and sandbox state management.
"""

import asyncio
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
)

from .config import CONFIG_NAME
from .sb_types import ConfigLine, ConfigLines, Envs

Environ = dict[str, str] | os._Environ
"""Type alias for environment variable mappings."""


def resolve_env_variables(s: str, envs: Environ | Envs) -> str:
    """Resolve environment variables in a string using bash-like syntax.

    Supports ${VAR} and ${VAR:-default} patterns for variable substitution.

    Args:
        s: String containing environment variable references.
        envs: Environment variables mapping.

    Returns:
        String with all environment variables resolved.

    Examples:
        >>> resolve_env_variables("${HOME}/file", {"HOME": "/home/user"})
        '/home/user/file'
        >>> resolve_env_variables("${PORT:-8000}", {})
        '8000'
    """
    pattern = re.compile(r"\$\{([^{}:-]+)(?::-([^{}]*))?\}")

    def replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        default_value = match.group(2)

        while "${" in var_name:
            var_name = resolve_env_variables(var_name, envs)
        if default_value is not None:
            while "${" in default_value:
                default_value = resolve_env_variables(default_value, envs)

        if default_value is None:
            default_value = ""
        value = envs.get(var_name, default_value)
        return value

    while re.search(r"\${.*}", s):
        s = pattern.sub(replace, s)
    return s


def substitute_env_vars(lines: list[str], env_vars: Environ | Envs) -> list[str]:
    """Substitute environment variables in a list of strings.

    Args:
        lines: List of strings containing environment variable references.
        env_vars: Environment variables mapping.

    Returns:
        List of strings with environment variables resolved.
    """
    return [resolve_env_variables(line, env_vars) for line in lines]


def substitute_config_env_vars(lines: ConfigLines, env_vars: Environ) -> ConfigLines:
    """Substitute environment variables in configuration lines.

    Args:
        lines: Configuration lines containing environment variable references.
        env_vars: Environment variables mapping.

    Returns:
        Configuration lines with environment variables resolved.
    """
    return [
        ConfigLine(resolve_env_variables(line, env_vars), path, ln)
        for line, path, ln in lines
    ]


def remove_config_comments(config: ConfigLines) -> ConfigLines:
    """Remove comments and template lines from configuration.

    Args:
        config: Configuration lines to process.

    Returns:
        Configuration lines with comments and templates removed.
    """
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


def remove_comments(config: list[str]) -> list[str]:
    """Remove comments from a list of strings.

    Args:
        config: List of strings to process.

    Returns:
        List of strings with comments removed.
    """
    processed_lines: list[str] = []

    for line in config:
        # Remove end-of-line comments while respecting quotes
        cleaned_line: str = _remove_comment(line.strip())

        # Filter out empty lines and lines that are full comments
        if cleaned_line and not cleaned_line.lstrip().startswith("#"):
            processed_lines.append(cleaned_line)

    return processed_lines


def _remove_comment(line: str) -> str:
    """Remove comments from a line while respecting quotes.

    Args:
        line: The line to process.

    Returns:
        Line without comment.
    """
    result: list[str] = []
    in_quotes: bool = False
    quote_char: str | None = None
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
    """Yield directories starting from given directory up to base.

    Args:
        path: Starting directory path.
        base: Base directory to stop at.

    Yields:
        Directory paths from starting directory up to base.

    Raises:
        IOError: If starting path is not found.
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


# %% -----------------------

# _sandboxed = contextvars.ContextVar("sanboxed", default=0)  FIXME: sandbox et is_in_sandbox?
_sandboxed = 0
_is_in_sandbox: int = 0


def is_in_sandbox() -> bool:
    """Check if currently executing inside a sandbox.

    Returns:
        True if inside sandbox, False otherwise.
    """
    global _is_in_sandbox
    # return _sandboxed.get() > 0
    return _is_in_sandbox > 0


def set_is_in_sandbox(value: bool) -> None:
    """Set sandbox execution state.

    Args:
        value: True to enter sandbox context, False to exit.
    """
    global _is_in_sandbox
    global _sandboxed
    if value:
        # _sandboxed.set(_sandboxed.get() + 1)
        _sandboxed += 1
        _is_in_sandbox += 1
    else:
        # _sandboxed.set(_sandboxed.get() - 1)
        _sandboxed -= 1
        _is_in_sandbox -= 1
        # assert _sandboxed.get() >= 0
        assert _sandboxed >= 0, f"{_sandboxed=}"


def find_config_for_module(module: str,config_name:str) -> Path | None:
    import importlib

    # The importlib.resources.files() approach requires importing the file. We don't want to do that when
    # invoking it via python-sb. It's too soon. The alternative is to search for the file itself.
    try:
        spec_module = importlib.util.find_spec(module)
        if spec_module and spec_module.origin:
            config = Path(spec_module.origin).parent / config_name
            if config.exists():
                return config
        return None
    except FileNotFoundError:
        return None
    except ModuleNotFoundError:
        return None


SyncOrAsyncFunc = Callable[[], None] | Callable[[], Awaitable[None]]


def get_callable_info(func: Callable[..., Any]) -> tuple[str | None, str | None]:
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
    module_name: str | None = None
    callable_name: str | None = None

    # Get the module name using inspect.getmodule()
    # This works well for functions, methods, and class methods
    module_obj = inspect.getmodule(func)
    if module_obj and module_obj.__spec__:
        module_name = module_obj.__spec__.name

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
    elif callable(func):
        # It's an instance of a class with a __call__ method
        callable_name = func.__class__.__qualname__
        if callable_name:
            callable_name += ".__call__"
    return module_name, callable_name


mixed_sync_and_async_error = (
    "It's not possible to mix synchronous and asynchronous sandbox functions. "
    "Therefore, you must only use annotated asynchronous functions with an asynchronous sandbox."
)


def check_mixte_async_async() -> None:
    """Check for mixed synchronous and asynchronous execution contexts.

    Raises:
        RuntimeError: If mixing sync and async sandbox functions.
    """
    try:
        if asyncio.get_running_loop():
            raise RuntimeError(mixed_sync_and_async_error)
    except RuntimeError as e:
        if str(e) == "no running event loop":
            pass  # Ignore
        else:
            raise


def follow_links_executable(executable: Path, all_paths: set[Path]) -> set[Path]:
    """Follow symlinks for executable paths and add to paths set.

    Args:
        executable: Path to executable to follow.
        all_paths: Set of paths to add discovered paths to.

    Raises:
        RuntimeError: If unable to resolve executable symlink.
    """
    if executable.parents[0].name == "bin":
        if str(executable.parent.parent) not in all_paths:
            all_paths.add(executable.parent.parent)
        else:
            return all_paths
    else:
        if executable not in all_paths:
            all_paths.add(executable)
        else:
            return all_paths
    if executable.is_symlink():
        try:
            follow_links_executable(executable.resolve(strict=True), all_paths)
        except FileNotFoundError as e:
            raise RuntimeError(
                "Impossible to resolve the sys.executable `%s`", sys.executable
            ) from e
    return all_paths
