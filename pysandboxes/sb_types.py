"""Type definitions for PySandboxes.

This module provides common type aliases and data structures used throughout
the PySandboxes framework for configuration, arguments, and environment handling.
"""

from pathlib import Path
from typing import NamedTuple

from .immutable_dict import ImmutableDict


class ConfigLine(NamedTuple):
    """Represents a single configuration rule with metadata.

    Attributes:
        rule: The configuration rule string.
        path: Path to the file containing this rule.
        ln: Line number where this rule appears.
    """

    rule: str
    path: Path
    ln: int


ConfigLines = list[ConfigLine]
"""Type alias for a list of configuration lines."""

Args = list[str]
"""Type alias for command line arguments."""

Envs = ImmutableDict[str, str]
"""Type alias for environment variables mapping."""
