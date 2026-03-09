# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Logging utilities and error formatting for PySandboxes.

This module provides logging configuration and utility functions for formatting
error messages, file paths, and configuration references throughout the framework.
"""

import logging
from pathlib import Path
from typing import Sequence

from .sb_types import ConfigLine

pysandboxes_logger = logging.getLogger("Pysandboxes")

ErrorMsg = tuple[str, Path, int]
"""Type alias for error message tuples containing message, path, and line number."""


def make_relative_path(path: Path | None) -> str:
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
    try:
        rel_path = str(path.absolute().relative_to(Path.cwd()))
    except ValueError:
        # File not relative to cwd
        try:
            path.absolute().relative_to(Path.home())
            rel_path = "~" + str(path.absolute())[len(str(Path.home())) :]
        except ValueError:
            # File not in home
            rel_path = str(path.absolute())
    return rel_path


def format_ruleref(rule: ConfigLine) -> str:
    """Format a configuration rule reference for error messages.

    Args:
        rule: The configuration line to format.

    Returns:
        A formatted string showing file path and line number.
    """
    if rule.path == Path():
        path = "<arg>"
    else:
        path = make_relative_path(rule.path)
    if rule.ln == 0:
        return path
    else:
        return f"{path}({rule.ln})"


def format_error_list(errors: Sequence[str]) -> str:
    """Format a list of error messages into a human-readable string.

    Args:
        errors: Sequence of error message strings.

    Returns:
        A formatted string with proper conjunction usage.
    """
    return (
        errors[0] if len(errors) == 1 else ", ".join(errors[:-1]) + " and " + errors[-1]
    )


def config_log(log_level: int, format: str | None = None) -> None:
    handlers: list[logging.Handler] = []
    try:
        # from rich.console import Console
        # from rich.logging import RichHandler
        #
        # # Active RichHandler if possible.
        # handlers.append(
        #     RichHandler(
        #         console=Console(stderr=True),
        #         rich_tracebacks=False,
        #         log_time_format="[%X]",
        #         show_time=True,
        #     )
        # )
        # if not format:
        #     format = "[%(process)d] %(message)s"
        pass
    except ImportError:
        if not format:
            format = "%(levelname)-5s [%(process)d] %(name)s: %(message)s"
        handlers = [logging.StreamHandler()]
        handlers[0].setFormatter(logging.Formatter(format))
    logging.basicConfig(
        force=True,
        level=log_level,
        format=format,
        handlers=handlers,
    )
