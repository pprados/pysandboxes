# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Pickle import guard for PySandboxes.

This module implements pickle sandboxing by intercepting pickle imports and
controlling deserialization. It enforces a whitelist-based security model where
only explicitly allowed classes can be unpickled.

Security Model:
- Default-deny: All pickle imports are blocked by default
- Caller verification: Only pysandboxes internal modules can import pickle
- Safe unpickling: Provides safe_unpickle() with class whitelist
- Restricted find_class: Prevents arbitrary code execution during unpickling

Limitations:
This is a Python-level protection that does NOT defend against:
- Malicious __reduce__ methods in whitelisted classes
- Attacks that bypass find_class mechanism
- Pickle protocol version exploits

For complete protection, combine with OS-level sandboxing and code review of
whitelisted classes.

Example:
    ```python
    from pysandboxes.guard_pickle import safe_unpickle
    data = safe_unpickle(blob, allowed_classes=['MyDataClass'])
    ```
"""

import inspect
import io
import logging
import pickle
import sys
from typing import Any, NamedTuple

logger = logging.getLogger(__name__)

# Store original pickle.loads for restoration during testing
_original_pickle_loads = pickle.loads


class PickleRules(NamedTuple):
    """Rules for controlling pickle deserialization.

    Attributes:
        allowed_modules: Tuple of module name prefixes allowed to import pickle.
        allowed_classes: Tuple of class names allowed during unpickling.
    """

    allowed_modules: tuple[str, ...]
    allowed_classes: tuple[str, ...]


def parse_rules(
    config: list[str],
) -> tuple[PickleRules, list[str]]:
    """Parse pickle rules from configuration.

    Args:
        config: Configuration lines to process.

    Returns:
        Tuple of parsed pickle rules and remaining config lines.
    """
    allowed_classes: list[str] = []
    ignore_rules: list[str] = []

    for rule in config:
        if rule.startswith("pickle-class="):
            value = rule.split("=", 1)[1]
            allowed_classes.extend([c.strip() for c in value.split(",")])
        else:
            ignore_rules.append(rule)

    if "*" in allowed_classes:
        allowed_classes = ["*"]

    rules = PickleRules(
        allowed_modules=("pysandboxes",),
        allowed_classes=tuple(allowed_classes),
    )
    return rules, ignore_rules


def patch_rules() -> None:
    """Apply pickle security rules (not used in this version)."""
    pass


class PickleImportBlocker:
    """Meta path finder that blocks pickle imports outside pysandboxes."""

    def find_spec(self, fullname: str, path: Any = None, _target: Any = None) -> Any:
        """Find module spec, blocking pickle imports from non-pysandboxes code.

        Args:
            fullname: Full name of the module being imported.
            path: Search path (unused).
            target: Target module (unused).

        Returns:
            None to allow normal import, or raises to block.
        """
        if fullname != "pickle":
            return None

        # Get the calling frame
        frame = inspect.currentframe()
        if frame is None or frame.f_back is None:
            return None

        caller_frame = frame.f_back
        caller_module = caller_frame.f_globals.get("__name__", "")

        # Allow only pysandboxes internal modules
        if not caller_module.startswith("pysandboxes"):
            raise ImportError(
                f"pickle import denied from {caller_module}. " "Use pysandboxes.guard_pickle.safe_unpickle() instead."
            )

        return None


class _RestrictedUnpickler(pickle.Unpickler):
    """Unpickler with restricted find_class."""

    def __init__(self, fp: Any, allowed_classes: tuple[str, ...]):
        """Initialize unpickler with allowed classes.

        Args:
            fp: File-like object containing pickled data.
            allowed_classes: Tuple of allowed class names.
        """
        super().__init__(fp)
        self.allowed_classes = allowed_classes

    def find_class(self, module: str, name: str) -> type[Any]:
        """Find class with whitelist restriction.

        WARNING: This only controls which classes can be instantiated. It does NOT
        prevent code execution via __reduce__ or __setstate__ methods in whitelisted
        classes. Whitelisted classes are trusted to be safe. Audit all whitelisted
        classes for potentially dangerous deserialization hooks.

        Args:
            module: Module name being unpickled.
            name: Class name being unpickled.

        Returns:
            The class if allowed.

        Raises:
            pickle.UnpicklingError: If class is not in whitelist.
        """
        if "*" in self.allowed_classes:
            # Allow all classes if "*" is in whitelist (testing only)
            return getattr(__import__(module, fromlist=[name]), name)

        if name not in self.allowed_classes:
            # Raising the stdlib error type, not deserializing
            raise pickle.UnpicklingError(f"Class {module}.{name} not in whitelist. Allowed: {self.allowed_classes}")

        # Additional safety: only allow safe builtins and whitelisted modules
        if module == "builtins":
            safe_builtins = {
                "dict",
                "list",
                "tuple",
                "str",
                "int",
                "float",
                "bool",
                "bytes",
                "bytearray",
                "frozenset",
                "set",
                "None",
            }
            if name not in safe_builtins:
                # Raising the stdlib error type, not deserializing
                raise pickle.UnpicklingError(f"Builtin {name} not allowed (potential RCE vector)")
        elif not module.startswith(("pysandboxes", "__main__")):
            # Raising the stdlib error type, not deserializing
            raise pickle.UnpicklingError(f"Module {module} not trusted. Only pysandboxes modules allowed.")

        return getattr(__import__(module, fromlist=[name]), name)


def safe_unpickle(
    data: bytes,
    allowed_classes: list[str] | tuple[str, ...] | None = None,
) -> Any:
    """Safely unpickle data with class whitelist.

    CRITICAL: Whitelisted classes MUST be audited for safe __reduce__ implementations.
    A class with a malicious __reduce__ method can execute arbitrary code during
    unpickling, even if whitelisted. Example:
        class BadClass:
            def __reduce__(self):
                return (os.system, ("rm -rf /",))  # Executed on unpickle!

    Only whitelist classes you fully control and have audited.

    Args:
        data: Pickled data to unpickle.
        allowed_classes: List of class names allowed during unpickling.
                        Defaults to empty tuple (only safe builtins).

    Returns:
        Unpickled object.

    Raises:
        pickle.UnpicklingError: If unpickling is blocked by whitelist.
    """
    if allowed_classes is None:
        allowed_classes = ()
    elif isinstance(allowed_classes, list):
        allowed_classes = tuple(allowed_classes)

    # Use BytesIO and restricted unpickler
    fp = io.BytesIO(data)
    unpickler = _RestrictedUnpickler(fp, allowed_classes)
    return unpickler.load()


def _patch_pickle_loads() -> None:
    """Patch pickle.loads to block unsafe deserialization.

    Replaces pickle.loads with a function that raises an error,
    forcing code to use safe_unpickle() instead.
    """

    def blocked_loads(*_args: Any, **_kwargs: Any) -> Any:
        raise ImportError(
            "pickle.loads() is blocked for security. "
            "Use pysandboxes.guard_pickle.safe_unpickle() with explicit class whitelist instead. "
            "Allowed classes: safe_unpickle(..., allowed_classes=['ClassName1', 'ClassName2'])"
        )

    # Replace pickle.loads
    pickle.loads = blocked_loads  # type: ignore[assignment]
    logger.info("pickle.loads() patched to block unsafe deserialization")


def activate_import_guard() -> None:
    """Activate pickle security guards.

    Installs both import blocker and patches pickle.loads to force use of safe_unpickle().
    Should be called once during sandbox initialization.
    """
    blocker = PickleImportBlocker()
    if blocker not in sys.meta_path:
        sys.meta_path.insert(0, blocker)

    # Patch pickle.loads if it hasn't been patched yet
    if not hasattr(pickle.loads, "__wrapped__"):
        _patch_pickle_loads()

    logger.info("Pickle security guards activated")


def _deactivate_guard_pickle() -> None:
    """Deactivate pickle guards (for testing).

    Removes the import blocker from sys.meta_path and restores original pickle.loads.
    """
    sys.meta_path[:] = [item for item in sys.meta_path if not isinstance(item, PickleImportBlocker)]
    # Restore original pickle.loads
    pickle.loads = _original_pickle_loads  # type: ignore[assignment]
    logger.info("Pickle guards deactivated")
