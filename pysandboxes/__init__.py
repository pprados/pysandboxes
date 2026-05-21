# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""PySandboxes: Python Security Framework.

This package provides sandbox environments for executing untrusted Python code safely.
It uses a multi-layered defense-in-depth security architecture combining Python API
patching with OS-level containers.

The main API consists of:
- @sandbox decorator for function-level sandboxing
- sandboxes() context manager for process-level sandboxing
- run() function for running coroutines in sandboxes
- Learning mode for automatic security rule generation

Example:
    Basic function sandboxing:
    ```python
    from pysandboxes import sandbox

    @sandbox
    def untrusted_function():
        # This code runs in a sandbox
        return "safe result"
    ```

    Context manager usage:
    ```python
    from pysandboxes import sandboxes

    with sandboxes():
        # All code in this block runs sandboxed
        result = some_function()
    ```
"""

from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .e import (
        ConfigSyntaxError,  # noqa: F401
        RuleApiPermissionError,  # noqa: F401
        RuleAttributeError,  # noqa: F401
        RuleFileNotFoundError,  # noqa: F401
        RuleModuleNotFoundError,  # noqa: F401
        RulePermissionError,  # noqa: F401
        RuleSocketConnectionRefusedError,  # noqa: F401
        SandBoxError,  # noqa: F401
    )
    from .sandboxes_api import is_in_sandbox, run, sandbox, sandboxes  # noqa: F401

_api = {"sandboxes", "sandbox", "run", "is_in_sandbox"}
_exception = {
    "SandBoxError",
    "ConfigSyntaxError",
    "RuleFileNotFoundError",
    "RulePermissionError",
    "RuleSocketConnectionRefusedError",
    "RuleModuleNotFoundError",
    "RuleAttributeError",
    "RuleApiPermissionError",
}

_cli = {
    "cli",
}

# Explicit list to avoid pyright warning about unsupported __all__ operation
# Note: Exceptions are loaded via __getattr__ (lazy loading)
__all__ = [
    "sandboxes",
    "sandbox",
    "SandBoxError",
    "ConfigSyntaxError",
    "RuleFileNotFoundError",
    "RulePermissionError",
    "RuleSocketConnectionRefusedError",
    "RuleModuleNotFoundError",
    "RuleAttributeError",
    "RuleApiPermissionError",
]


class LazySandboxesProxy:
    """Lazy loading proxy to handle circular imports.

    This class delays the import of sandbox modules until they are actually
    accessed, preventing circular import issues while maintaining a clean API.

    Attributes:
        modules: Cached mapping of attribute names to their containing modules.
    """

    def __init__(self) -> None:
        """Initialize the proxy with no cached modules."""
        self.modules: dict[str, ModuleType] | None = None

    def __getattr__(self, name: str) -> Any:
        """Intercept attribute access and import modules as needed.

        Args:
            name: The name of the attribute being accessed.

        Returns:
            The requested attribute from the appropriate module.

        Raises:
            AttributeError: If the attribute is not found in any module.
        """
        if not self.modules:
            import importlib

            module_api = importlib.import_module(".sandboxes_api", package=__name__)
            module_exception = importlib.import_module(".e", package=__name__)
            self.modules = {api: module_api for api in _api} | {
                api: module_exception for api in _exception
            }
        if name in self.modules:
            return getattr(self.modules[name], name)
        else:
            raise AttributeError(f"{name} not found")


_sandboxes = LazySandboxesProxy()

os_sandbox: str = "none"


def __getattr__(name: str) -> Any:
    """Module-level attribute access proxy.

    Args:
        name: The name of the attribute being accessed.

    Returns:
        The requested attribute from the sandboxes proxy.
    """
    return _sandboxes.__getattr__(name)
