# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Exception classes for PySandboxes.

This module centralizes all exception types to provide better stack traces
and consistent error handling throughout the framework.
"""


class SandBoxError(RuntimeError):
    """Base exception class for all sandbox-related errors."""

    pass


class ConfigSyntaxError(SandBoxError):
    """Exception raised when configuration file has syntax errors.

    Attributes:
        message: The main error message.
        errors: List of specific syntax errors found.
    """

    def __init__(self, message: str, errors: list[str]) -> None:
        """Initialize the exception with message and error list.

        Args:
            message: The main error message.
            errors: List of specific syntax errors.
        """
        super().__init__()
        self.message = message
        self.errors = errors

    def __str__(self) -> str:
        """Return formatted error message with all errors listed.

        Returns:
            Formatted string with main message and all error details.
        """
        return self.message + "\n" + "\n".join(self.errors)


class RuleFileNotFoundError(FileNotFoundError, SandBoxError):
    """Exception raised when a file access is denied by sandbox rules."""

    pass


class RulePermissionError(PermissionError, SandBoxError):
    """Exception raised when a permission is denied by sandbox rules."""

    pass


class RuleSocketConnectionRefusedError(ConnectionRefusedError, SandBoxError):
    """Exception raised when a network connection is denied by sandbox rules."""

    pass


class RuleModuleNotFoundError(ModuleNotFoundError, SandBoxError):
    """Exception raised when a module import is denied by sandbox rules."""

    pass


class RuleAttributeError(AttributeError, SandBoxError):
    """Exception raised when an attribute access is denied by sandbox rules."""

    pass


class RuleApiPermissionError(PermissionError, SandBoxError):
    """Raised when a sensitive API call is denied by the API guard."""

    def __init__(self, qualname: str, category: str) -> None:
        """Initialize the exception with the denied call and its category.

        Args:
            qualname: Qualified name of the denied function.
            category: Registry category the function belongs to.
        """
        super().__init__(
            f"{qualname}() is denied by the API guard "
            f"(category: {category}).\n"
            f"Add `python-api=ALLOW:{qualname}` for this function "
            f"only, "
            f"or `python-api=ALLOW:{category}` for the whole category."
        )
        self.qualname = qualname
        self.category = category
