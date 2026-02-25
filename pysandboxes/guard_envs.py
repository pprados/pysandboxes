"""Environment variables access guard for PySandboxes.

This module implements environment variable sandboxing by intercepting and
controlling access to os.environ. It provides a whitelist-based security model
where only explicitly allowed environment variables are accessible.

The guard supports pattern matching, variable substitution, and learning mode
for automatic rule generation based on observed environment variable usage.
"""
import inspect
import logging
import os
import re
import threading
from pathlib import Path
from threading import Thread
from typing import Any, Callable, NamedTuple, cast
from weakref import WeakKeyDictionary

from .main_logger import ErrorMsg, format_ruleref
from .sb_types import ConfigLine, ConfigLines, Envs
from .tools import Environ, is_in_sandbox, resolve_env_variables

logger = logging.getLogger(__name__)


class EnvRule(NamedTuple):
    """Internal representation of an environment variable rule.

    Attributes:
        pattern: Compiled regex pattern to match variable names.
        ignore: Whether this is an ignore rule (blocks access).
        config: Configuration line where this rule was defined.
    """

    pattern: re.Pattern[str]
    ignore: bool
    config: ConfigLine


EnvsRules = tuple[EnvRule, ...]
"""Type alias for a tuple of environment variable rules."""

# Internal state for the file filter
_rules: EnvsRules = cast(EnvsRules, ())


def parse_rules(
        rules: ConfigLines,
        source_vars: Environ,
        errors: list[ErrorMsg],
) -> tuple[EnvsRules, Envs, ConfigLines]:
    """Process environment variable rules to create filtered environment.

    Args:
        rules: Configuration lines containing env rules.
        source_vars: Source environment variables to draw from.
        errors: List to collect parsing errors.

    Returns:
        Tuple containing parsed rules, filtered environment, and remaining config lines.
    """
    new_vars: dict[str, str] = {}
    ignore_rules: ConfigLines = []

    def substitute_value(value_pattern: str) -> str:
        return resolve_env_variables(value_pattern, source_vars)

    envs_rules = set()
    for orule in rules:
        if orule.rule.startswith("env="):
            # Remove prefix
            rule = ConfigLine(orule.rule[len("env="):], orule.path, orule.ln)

            if "=" not in rule.rule:
                errors.append(
                    (
                        f"{format_ruleref(orule)}: "
                        f"Detect a missing '=' in rule: {orule.rule}.",
                        rule.path,
                        rule.ln,
                    )
                )
                continue

            key_pattern, value_pattern = rule.rule.split("=", 1)

            # Case: Wildcard rule like *_API_KEY=${*_API_KEY}
            if "*" in key_pattern:
                # Convert wildcard to regex pattern
                regex_key = re.compile(re.escape(key_pattern).replace("\\*", ".*"))
                envs_rules.add(EnvRule(regex_key, False, orule))
                for source_key, source_value in source_vars.items():
                    if regex_key.match(source_key):
                        # The rule implies copying the matched key-value pairs
                        new_vars[source_key] = source_value
            # Case: Simple rule like key=value or key=${VAR}
            else:
                new_vars[key_pattern] = substitute_value(value_pattern)
                envs_rules.add(
                    EnvRule(re.compile(re.escape(key_pattern)), False, orule)
                )
        elif orule.rule.startswith("unenv="):
            remove_key = orule.rule[len("unenv="):]
            new_vars.pop(remove_key, None)
            envs_rules.add(EnvRule(re.compile(re.escape(remove_key)), True, orule))
        else:
            ignore_rules.append(orule)

    return tuple(envs_rules), Envs(new_vars), ignore_rules


class LearnEnviron(os._Environ):
    """Custom environment class that logs all accesses for learning mode.

    This class replaces os.environ to track which environment variables
    are accessed during execution, enabling automatic rule generation.
    Implements singleton pattern to ensure consistency.
    """

    _instance: "LearnEnviron | None" = None

    def __new__(
            cls,
    ) -> "LearnEnviron":
        """Create or return existing singleton instance.

        Returns:
            The singleton LearnEnviron instance.
        """
        # Implement a singleton
        if cls._instance is None:
            cls._instance = super(LearnEnviron, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize the learning environment if not already done."""
        # Initialize with the _original environment data
        if not hasattr(self, "_keys_used"):
            # super().__init__(original_environ)
            encodekey = os.environ.encodekey
            decodekey = os.environ.decodekey
            encodevalue = os.environ.encodevalue
            decodevalue = os.environ.decodevalue
            assert hasattr(os.environ, "_data")
            data = os.environ._data  # type: ignore[attr-defined]
            super().__init__(data, encodekey, decodekey, encodevalue, decodevalue)
            self._ignore_keys: WeakKeyDictionary[Thread,set[str]] = {}
            self._keys_used: set[str] = set()
            self._original_envs = os.environ

    def __iter__(self):
        frame = inspect.currentframe()
        if frame is not None:
            frame = frame.f_back.f_back
        root_iter = super().__iter__()

        self._ignore_keys[threading.current_thread()]=set()
        def _catch_for_all():
            for k in root_iter:
                iter_frame = inspect.currentframe()
                if iter_frame:
                    iter_frame = iter_frame.f_back.f_back
                if id(iter_frame) == id(frame):
                    self._ignore_keys[threading.current_thread()].add(k)
                yield k

        return _catch_for_all()  # TODO: items()

    def __getitem__(self, key: str) -> str:
        """Get environment variable and track access in learning mode.

        Args:
            key: Environment variable name.

        Returns:
            Environment variable value.

        Raises:
            KeyError: If environment variable doesn't exist.
        """
        try:
            result = super(LearnEnviron, self).__getitem__(key)
            ignore_keys:set[str]=self._ignore_keys.get(threading.current_thread(),set())
            if key not in ignore_keys:
                self._keys_used.add(key)
            else:
                ignore_keys.remove(key)
            return result
        except KeyError:
            raise

    def __setitem__(self, key: str, value: str) -> None:
        """Set environment variable and track access in learning mode.

        Args:
            key: Environment variable name.
            value: Environment variable value.
        """
        super(LearnEnviron, self).__setitem__(key, value)
        if is_in_sandbox():
            self._keys_used.add(key)

    def _clone(self) -> dict[str, str]:
        """Create a copy of the environment as a regular dictionary.

        Returns:
            Dictionary copy of all environment variables.
        """
        return {k: v for k, v in super().items()}

    def _get(self, key: str, default: Any = None) -> Any:
        """Get environment variable with default fallback.

        Args:
            key: Environment variable name.
            default: Default value if key doesn't exist.

        Returns:
            Environment variable value or default.
        """
        try:
            result = super(LearnEnviron, self).__getitem__(key)
            return result
        except KeyError:
            return default

    def _has(self, key: str) -> Any:
        """Check if environment variable exists.

        Args:
            key: Environment variable name.

        Returns:
            True if variable exists, False otherwise.
        """
        try:
            super(LearnEnviron, self).__getitem__(key)
            return True
        except KeyError:
            return False


def generate_rules() -> list[str]:
    """Generate environment variable rules from learning data.

    Creates configuration rules for all environment variables that were
    accessed during learning mode execution.

    Returns:
        List of env= configuration rule strings.
    """
    global _rules
    learn_env = LearnEnviron()  # Get singleton
    result = []
    for key in sorted(learn_env._keys_used):
        find = False
        for pat in _rules:
            if pat.pattern.match(key):
                find = True
                break
        if not find:
            result.append(f"env={key}=${{{key}}}")
    return result


def activate_guard(rules: EnvsRules) -> None:
    """Activate environment variable guard with specified rules.

    Args:
        rules: Environment variable access rules to enforce.
    """
    global _rules
    _rules = rules


def patch_rules(learning_path: Path | None) -> dict[str, Callable]:
    """Provide patch rules for environment variable monitoring.

    Args:
        learning_path: Path for learning mode configuration, None if disabled.

    Returns:
        Dictionary of module patches for environment monitoring.
    """
    if learning_path:

        def activate_learning_env_factory(x: Any) -> LearnEnviron:
            return LearnEnviron()

        return {"os.environ": activate_learning_env_factory}
    else:
        return {}
