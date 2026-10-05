# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Environment variables access guard for PySandboxes.

This module implements environment variable sandboxing by intercepting and
controlling access to os.environ. It provides a whitelist-based security model
where only explicitly allowed environment variables are accessible.

The guard supports pattern matching, variable substitution, and learning mode
for automatic rule generation based on observed environment variable usage.
"""

import logging
import os
import sys
import threading
from typing import Any, Callable, Generator, Iterator, NamedTuple, cast
from weakref import WeakKeyDictionary

from .guard_wraps import guard_wraps
from .main_logger import ErrorMsg, format_ruleref
from .sb_types import ConfigLine, ConfigLines, Envs
from .tools import Environ, GlobPattern, resolve_env_variables
from .tools import patch_factory as _f

logger = logging.getLogger(__name__)


class EnvRule(NamedTuple):
    """Internal representation of an environment variable rule.

    Attributes:
        pattern: Compiled glob matching variable names.
        ignore: Whether this is an ignore rule (blocks access).
        config: Configuration line where this rule was defined.
    """

    pattern: GlobPattern
    ignore: bool
    config: ConfigLine


EnvsRules = tuple[EnvRule, ...]
"""Type alias for a tuple of environment variable rules."""

# Internal state for the file filter
_rules: EnvsRules = cast(EnvsRules, ())


def _compile_key_pattern(key_pattern: str) -> GlobPattern:
    """Compile an environment key pattern, anchored on both ends.

    ``*`` is the only wildcard. `GlobPattern` matches over the whole key, so
    ``*_API_KEY`` does not forward ``ANY_API_KEY_AND_MORE``; the previous regex
    needed a trailing ``\\Z`` to say the same, because ``re.match()`` anchors the
    start only.
    """
    return GlobPattern(key_pattern)


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
            rule = ConfigLine(orule.rule[len("env=") :], orule.path, orule.ln)

            if "=" not in rule.rule:
                errors.append(
                    (
                        f"{format_ruleref(orule)}: " f"Detect a missing '=' in rule: {orule.rule}.",
                        rule.path,
                        rule.ln,
                    )
                )
                continue

            key_pattern, value_pattern = rule.rule.split("=", 1)

            # Case: Wildcard rule like *_API_KEY=${*_API_KEY}
            if "*" in key_pattern:
                # Convert wildcard to regex pattern
                regex_key = _compile_key_pattern(key_pattern)
                envs_rules.add(EnvRule(regex_key, False, orule))
                for source_key, source_value in source_vars.items():
                    if regex_key.match(source_key):
                        # The rule implies copying the matched key-value pairs
                        if source_value:  # Ignore empty value
                            new_vars[source_key] = source_value
            # Case: Simple rule like key=value or key=${VAR}
            else:
                v = substitute_value(value_pattern)
                # A "${...}" pattern forwards a host variable: an empty result
                # means the variable is unset, so the key must stay absent.
                # Creating it empty would make os.getenv(key, default) return ""
                # instead of the caller's default. A literal value is kept as
                # written, so "key in os.environ" is True (e.g. My_ENV for tests).
                if v or "${" not in value_pattern:
                    new_vars[key_pattern] = v
                envs_rules.add(EnvRule(_compile_key_pattern(key_pattern), False, orule))
        elif orule.rule.startswith("unenv="):
            remove_key = orule.rule[len("unenv=") :]
            new_vars.pop(remove_key, None)
            envs_rules.add(EnvRule(_compile_key_pattern(remove_key), True, orule))
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
            # Keys a scan yielded and that were not read back yet, in scan order
            self._scanned: WeakKeyDictionary[threading.Thread, list[str]] = WeakKeyDictionary()
            # Reads that match the scan order, so may be its read-back: learned if the order breaks
            self._unsure: WeakKeyDictionary[threading.Thread, list[str]] = WeakKeyDictionary()
            # The key a running scan just yielded
            self._yielded: WeakKeyDictionary[threading.Thread, str] = WeakKeyDictionary()
            self._keys_used: set[str] = set()
            self._original_envs = os.environ

    def __iter__(self) -> Iterator[str]:
        root_iter = super().__iter__()
        t = threading.current_thread()
        self._commit_unsure(t)
        scanned: list[str] = []
        self._scanned[t] = scanned

        def _catch_for_all() -> Generator[Any, None, None]:
            try:
                for k in root_iter:
                    scanned.append(k)
                    self._yielded[t] = k
                    yield k
            finally:
                self._yielded.pop(t, None)

        return _catch_for_all()

    def _commit_unsure(self, t: threading.Thread) -> None:
        """The scan order broke: the reads kept aside were real uses."""
        self._keys_used.update(self._unsure.pop(t, []))
        self._scanned.pop(t, None)

    def commit_unsure(self) -> None:
        """Learn the reads still kept aside, before the rules are generated."""
        for t in list(self._unsure.keys()):
            self._commit_unsure(t)

    def __getitem__(self, key: str) -> str:
        """Get environment variable and track access in learning mode.

        Args:
            key: Environment variable name.

        Returns:
            Environment variable value.

        Raises:
            KeyError: If environment variable doesn't exist.
        """
        result = super(LearnEnviron, self).__getitem__(key)
        t = threading.current_thread()
        scanned = self._scanned.get(t)
        # A scan reads a key back right after yielding it (``for k in os.environ: os.environ[k]``,
        # ``items()``), or lists every key first and reads them back in order (``dict(os.environ)``).
        # Neither is a use. Any other read is, like a key skipped by urllib's proxy scan read later.
        if scanned and key == scanned[-1] and self._yielded.get(t) == key:
            scanned.pop()
        elif scanned and key == scanned[0]:
            scanned.pop(0)
            self._unsure.setdefault(t, []).append(key)
        else:
            self._commit_unsure(t)
            self._keys_used.add(key)
            return result
        if not scanned:
            self._unsure.pop(t, None)  # The whole scan was read back
        return result

    def __setitem__(self, key: str, value: str) -> None:
        """Set environment variable and track access in learning mode.

        Args:
            key: Environment variable name.
            value: Environment variable value.
        """
        super(LearnEnviron, self).__setitem__(key, value)
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


class LearnEnvironBytes(os._Environ):
    """Bytes view of the learning environment, tracking reads like os.environ."""

    def __init__(self) -> None:
        environ = os.environ
        assert isinstance(environ, LearnEnviron)
        super().__init__(
            environ._data,  # type: ignore[attr-defined]
            os.environb.encodekey,
            os.environb.decodekey,
            os.environb.encodevalue,
            os.environb.decodevalue,
        )

    def __getitem__(self, key: bytes) -> bytes:
        value = os.environ[os.fsdecode(key)]
        return os.fsencode(value)

    def __setitem__(self, key: bytes, value: bytes) -> None:
        os.environ[os.fsdecode(key)] = os.fsdecode(value)

    def __delitem__(self, key: bytes) -> None:
        del os.environ[os.fsdecode(key)]

def generate_rules() -> list[str]:
    """Generate environment variable rules from learning data.

    Creates configuration rules for all environment variables that were
    accessed during learning mode execution.

    Returns:
        List of env= configuration rule strings.
    """
    global _rules
    learn_env = LearnEnviron()  # Get singleton
    learn_env.commit_unsure()
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


def _wrap_os_putenv(func: Callable) -> Callable:
    @guard_wraps(func)
    def wrapper(name: str | bytes, value: str) -> None:
        assert isinstance(os.environ, LearnEnviron)
        if isinstance(name, bytes):
            str_name = name.decode(sys.getfilesystemencoding())
        else:
            str_name = name
        os.environ._keys_used.add(str_name)
        func(name, value)

    return wrapper


def _wrap_os_getenv(func: Callable) -> Callable:
    @guard_wraps(func)
    def wrapper(key: str | bytes, default: str | None = None) -> str:
        assert isinstance(os.environ, LearnEnviron)
        if isinstance(key, bytes):
            str_name = key.decode(sys.getfilesystemencoding())
        else:
            str_name = key
        os.environ._keys_used.add(str_name)
        return func(key, default)

    return wrapper


def _wrap_os_getenvb(func: Callable) -> Callable:
    @guard_wraps(func)
    def wrapper(key: bytes, default: bytes | None = None) -> bytes:
        assert isinstance(os.environ, LearnEnviron)
        os.environ._keys_used.add(os.fsdecode(key))
        return func(key, default)

    return wrapper


def _wrap_os_unsetenv(func: Callable) -> Callable:
    @guard_wraps(func)
    def wrapper(name: str) -> None:
        assert isinstance(os.environ, LearnEnviron)
        if isinstance(name, bytes):
            str_name = name.decode(sys.getfilesystemencoding())
        else:
            str_name = name
        os.environ._keys_used.add(str_name)
        func(name)

    return wrapper


def patch_rules(learn: bool) -> dict[str, Callable]:
    """Provide patch rules for environment variable monitoring.

    Args:
        learn: Use learn mode?

    Returns:
        Dictionary of module patches for environment monitoring.
    """
    if learn:

        def activate_learning_env_factory(x: Any) -> LearnEnviron:
            os.environ = LearnEnviron()  # noqa: B003
            return os.environ

        patches = {
            "os.environ": activate_learning_env_factory,
            "os.getenv": _f(_wrap_os_getenv),
            "os.putenv": _f(_wrap_os_putenv),
            "os.unsetenv": _f(_wrap_os_unsetenv),
        }
        if hasattr(os, "environb"):
            patches["os.environb"] = lambda _: LearnEnvironBytes()
            patches["os.getenvb"] = _f(_wrap_os_getenvb)
        return patches
    else:
        return {}


if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:

    def _deactivate_guard_envs() -> None:
        """Return the guard to its pre-arming state.

        ``_rules`` only feeds ``generate_rules()``, so leaving it set makes a later
        learning run under-report the variables it saw. Nothing else here needs
        undoing: outside learning mode ``patch_rules`` installs nothing, and the
        ``env=`` whitelist is applied when the sandbox is spawned, not in-process.
        A test that installs a ``LearnEnviron`` over ``os.environ`` restores it
        itself -- that replacement belongs to the test, not to this guard.
        """
        global _rules
        _rules = cast(EnvsRules, ())
