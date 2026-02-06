from importlib import metadata
from typing import List

from .sandboxes import sandboxes, sandbox, run

try:
    __version__ = metadata.version(__package__)
except metadata.PackageNotFoundError:
    # Case where package metadata is not available.
    __version__ = ""

__all__ = [
    "sandbox",
    "run",
    "sandboxes",
    "SandBoxError",
]

# All the exceptions are here, to have a better stack trace.
class SandBoxError(RuntimeError):
    pass

class ConfigSyntaxError(SandBoxError):
    def __init__(self, message: str, errors: List[str]):
        super().__init__()
        self.message = message
        self.errors = errors

    def __str__(self):
        return (self.message + "\n" +
                "\n".join(self.errors))

class RuleFileNotFoundError(FileNotFoundError, SandBoxError):
    pass


class RulePermissionError(PermissionError, SandBoxError):
    pass

class RuleSocketConnectionRefusedError(ConnectionRefusedError, SandBoxError):
    pass

class RuleModuleNotFoundError(ModuleNotFoundError, SandBoxError):
    pass


class RuleAttributeError(AttributeError, SandBoxError):
    pass