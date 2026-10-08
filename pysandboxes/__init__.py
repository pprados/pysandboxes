# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""PySandboxes: Python Security Framework.

This package provides sandbox environments for executing untrusted Python code safely.
It uses a multi-layered defense-in-depth security architecture combining Python API
patching with an OS boundary enforced by the kernel: one provider among `none`,
`subprocess`, `landlock`, `bwrap`, `firejail`, `unshare` and `qemu`, selected by the
`os-sandbox` directive. Docker and Podman are not providers of their own: a container
runs the `unshare` provider.

The main API consists of:
- `sandbox`, the decorator that runs a function in the sandbox
- `sandboxes`, the context manager, synchronous or asynchronous, that starts and stops it
- `run`, the `asyncio.run()` counterpart that starts the sandbox around a coroutine
- `is_in_sandbox`, to tell the sandboxed process from the calling one
- `guarded_eval`, to evaluate a source string under the `eval-*` rules
- the learning mode, started with `learn=".py-sandboxes"`, which writes the rules the
  application needs

Every exception of the framework derives from `SandBoxError`, and each denial also from the
built-in exception the same failure would raise without a sandbox:
- `RuleFileNotFoundError`: a path not exposed to the sandbox, or hidden from it
- `RulePermissionError`: a write to a path the sandbox may only read
- `RuleSocketConnectionRefusedError`: a network connection not allowed
- `RuleModuleNotFoundError`: an import not allowed
- `RuleApiPermissionError`: a sensitive API call denied by the API guard
- `EvalSyntaxRejected`, `RuleEvalPermissionError`: a dynamically evaluated source outside
  the `eval-*` rules, or refused by a runtime guard
- `ConfigSyntaxError`: a malformed configuration file
- `SandBoxProtocolError`: a failed dialogue with the sandbox process, not the code it ran
- `SandBoxBaseExceptionError`: the sandboxed function raised `SystemExit`, `KeyboardInterrupt`
  or another `BaseException`, which is never re-raised as itself in the caller
- `RestrictedUnpicklingError`: a result or exception from the sandbox that the transport
  refuses to deserialize

`EvalInterrupted`, raised inside evaluated code when a budget or the timeout runs out,
derives from `BaseException` instead, so that the evaluated code cannot catch it:
`except SandBoxError:` does not catch a timeout either.
`sandbox_denials` returns the denials that caused an exception.

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
        # Only @sandbox-decorated calls made in this block run sandboxed
        result = some_function()
    ```
"""

from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .e import (
        ConfigSyntaxError,  # noqa: F401
        EvalInterrupted,  # noqa: F401
        EvalSyntaxRejected,  # noqa: F401
        RestrictedUnpicklingError,  # noqa: F401
        RuleApiPermissionError,  # noqa: F401
        RuleEvalPermissionError,  # noqa: F401
        RuleFileNotFoundError,  # noqa: F401
        RuleModuleNotFoundError,  # noqa: F401
        RulePermissionError,  # noqa: F401
        RuleSocketConnectionRefusedError,  # noqa: F401
        SandBoxBaseExceptionError,  # noqa: F401
        SandBoxError,  # noqa: F401
        SandBoxProtocolError,  # noqa: F401
        sandbox_denials,  # noqa: F401
    )
    from .guard_eval import guarded_eval  # noqa: F401
    from .sandboxes_api import is_in_sandbox, run, sandbox, sandboxes  # noqa: F401

_api = {"sandboxes", "sandbox", "run", "is_in_sandbox"}
# guarded_eval lives in guard_eval, not in sandboxes_api, so the lazy proxy
# needs a third module group rather than an addition to _api.
_eval = {"guarded_eval"}
_exception = {
    "SandBoxError",
    "SandBoxProtocolError",
    "SandBoxBaseExceptionError",
    "sandbox_denials",
    "ConfigSyntaxError",
    "RuleFileNotFoundError",
    "RulePermissionError",
    "RuleSocketConnectionRefusedError",
    "RuleModuleNotFoundError",
    "RuleApiPermissionError",
    "EvalSyntaxRejected",
    "EvalInterrupted",
    "RuleEvalPermissionError",
    "RestrictedUnpicklingError",
}

# Explicit list to avoid pyright warning about unsupported __all__ operation
# Note: Exceptions are loaded via __getattr__ (lazy loading)
__all__ = [
    "sandboxes",
    "sandbox",
    "run",
    "is_in_sandbox",
    "SandBoxError",
    "ConfigSyntaxError",
    "RuleFileNotFoundError",
    "RulePermissionError",
    "RuleSocketConnectionRefusedError",
    "RuleModuleNotFoundError",
    "RuleApiPermissionError",
    "SandBoxProtocolError",
    "SandBoxBaseExceptionError",
    "sandbox_denials",
    "guarded_eval",
    "EvalSyntaxRejected",
    "EvalInterrupted",
    "RuleEvalPermissionError",
    "RestrictedUnpicklingError",
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
            module_guard_eval = importlib.import_module(".guard_eval", package=__name__)
            self.modules = (
                {api: module_api for api in _api}
                | {api: module_exception for api in _exception}
                | {api: module_guard_eval for api in _eval}
            )
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
