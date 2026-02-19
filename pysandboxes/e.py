# All the exceptions are here, to have a better stack trace.
from typing import List


class SandBoxError(RuntimeError):
    pass


class ConfigSyntaxError(SandBoxError):
    def __init__(self, message: str, errors: List[str]):
        super().__init__()
        self.message = message
        self.errors = errors

    def __str__(self) -> str:
        return self.message + "\n" + "\n".join(self.errors)


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
