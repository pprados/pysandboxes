# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Logging utilities and error formatting for PySandboxes.

This module provides logging configuration and utility functions for formatting
error messages, file paths, and configuration references throughout the framework.
"""

import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from ._contracts import ensure, post, pre
from .sb_types import ConfigLine

pysandboxes_logger = logging.getLogger("Pysandboxes")

ErrorMsg = tuple[str, Path, int]
"""Type alias for error message tuples containing message, path, and line number."""


@post(lambda result: isinstance(result, str) and result != "")
@ensure(lambda path, result: path is not None or result == "None")
def make_relative_path(path: Path | str | None) -> str:
    """Convert an absolute path to a relative path for display.

    Tries to make the path relative to current working directory, then home
    directory, falling back to absolute path if neither works.

    Args:
        path: The path to make relative.

    Returns:
        A string representation of the relative path.
    """
    if path is None:
        return "None"
    if isinstance(path, str):
        path = Path(path)
    try:
        rel_path = str(path.absolute().relative_to(Path.cwd()))
    except ValueError:
        # File not relative to cwd
        try:
            original_env = getattr(os.environ, "_original_envs", os.environ)
            home = original_env.get("HOME") or original_env.get("USERPROFILE")
            home_path = Path(home) if home else Path.home()
            path.absolute().relative_to(home_path)
            rel_path = "~" + str(path.absolute())[len(str(home_path)) :]
        except (ValueError, RuntimeError):
            # File not in home, or no home at all (a qemu guest has neither HOME nor a
            # passwd entry, and Path.home() raises RuntimeError there)
            rel_path = str(path.absolute())
    return rel_path


@post(lambda result: result != "")
@ensure(lambda rule, result: rule.ln == 0 or result.endswith(f"({rule.ln})"))
@ensure(lambda rule, result: rule.path != Path() or result.startswith("<arg>"))
def format_ruleref(rule: ConfigLine) -> str:
    """Format a configuration rule reference for error messages.

    Args:
        rule: The configuration line to format.

    Returns:
        A formatted string showing file path and line number.
    """
    empty_path = rule.path == Path() or (isinstance(rule.path, str) and rule.path.strip() in ("", "."))
    if empty_path:
        path = "<arg>"
    else:
        path = make_relative_path(rule.path)
    if rule.ln == 0:  # pragma: no mutate
        return path
    else:
        return f"{path}({rule.ln})"


@pre(lambda errors: len(errors) >= 1)
@ensure(lambda errors, result: all(error in result for error in errors))
@ensure(lambda errors, result: len(errors) != 1 or result == errors[0])
def format_error_list(errors: Sequence[str]) -> str:
    """Format a list of error messages into a human-readable string.

    Args:
        errors: Sequence of error message strings.

    Returns:
        A formatted string with proper conjunction usage.
    """
    errors = sorted(errors)
    return errors[0] if len(errors) == 1 else ", ".join(errors[:-1]) + " and " + errors[-1]  # pragma: no mutate


@ensure(lambda log_level, format=None, use_rich=False, result=None: logging.getLogger().level == log_level)
@ensure(lambda log_level, format=None, use_rich=False, result=None: len(logging.getLogger().handlers) >= 1)
def config_log(log_level: int, format: str | None = None, use_rich: bool = False) -> None:
    handlers: list[logging.Handler] = []
    # rich queries kernel32 through ctypes on Windows, which the API guard denies
    if use_rich and sys.platform != "win32":  # pragma: no mutate
        try:
            from rich.console import Console
            from rich.logging import RichHandler

            # Active RichHandler if possible.
            handlers.append(
                RichHandler(
                    console=Console(stderr=True),
                    rich_tracebacks=False,
                    log_time_format="[%X]",
                    show_time=True,
                )
            )
            if not format:
                format = "[%(process)d] %(message)s"
            # raise ImportError("")
        except ImportError:
            pass  # Ignore

    if not format:
        format = "%(levelname)-5s [%(process)d] %(name)s: %(message)s"
    if not handlers:
        handlers = [logging.StreamHandler()]
        handlers[0].setFormatter(logging.Formatter(format))
    logging.basicConfig(level=log_level, format=format, handlers=handlers, force=True)
