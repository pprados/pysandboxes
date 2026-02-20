from types import ModuleType
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .e import (
        ConfigSyntaxError,  # noqa: F401
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
}

_cli = {
    "cli",
}

__all__ = list(_api | _exception)


class LazySandboxesProxy:
    """
    Manage circular import
    """

    def __init__(self) -> None:
        # Le module n'est pas encore importé, juste son nom est stocké
        self.modules: dict[str, ModuleType] | None = None

    def __getattr__(self, name: str) -> Any:
        """
        Intercepte l'accès à un attribute et importe le module si nécessaire.
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


def __getattr__(name: str) -> Any:
    return _sandboxes.__getattr__(name)
