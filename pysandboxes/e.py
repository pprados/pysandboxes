# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Exception classes for PySandboxes.

This module centralizes all exception types to provide better stack traces
and consistent error handling throughout the framework.
"""


class SandBoxError(RuntimeError):
    """Base exception class for all sandbox-related errors."""

    pass


class SandBoxProtocolError(SandBoxError):
    """Raised when the dialogue with the sandbox fails, not the code it ran.

    The transport reports two unrelated kinds of failure to the caller: an
    exception raised by the sandboxed function, which is rebuilt as itself, and
    a failure of the exchange -- no answer within the RPC timeout, a stream that
    ended without a result, a call the sandbox cancelled, or a sandbox that
    could not transport its own exception. Only the second kind uses this class,
    so `except SandBoxProtocolError` never catches an application error and a
    caller can tell "my code was refused" from "the sandbox stopped answering".

    A sandboxed function raising SandBoxError, or any other RuntimeError, still
    reaches the caller as that exception.
    """


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

    def __reduce__(self) -> tuple[type, tuple[str, list[str]]]:
        """Rebuild the exception from its own attributes.

        ``BaseException.__reduce__`` replays ``args``, which this class does not
        populate. Without this, unpickling calls ``__init__`` with the wrong
        arity and the exception is lost while being transported.
        """
        return self.__class__, (self.message, self.errors)


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

    def __reduce__(self) -> tuple[type, tuple[str, str]]:
        """Rebuild the exception from its own attributes.

        ``BaseException.__reduce__`` replays ``args``, which here holds the
        formatted message instead of the two constructor parameters. Without
        this, a denial raised inside the sandbox cannot be unpickled by the
        caller: the transport loses it and the call ends on a timeout instead
        of on the refusal.
        """
        return self.__class__, (self.qualname, self.category)


_DENIALS_ATTRIBUTE = "__pysandboxes_denials__"


def attach_sandbox_denials(exception: BaseException) -> None:
    """Record on ``exception`` the sandbox denials that caused it.

    A library between the guard and the caller routinely rewrites the reason a
    call failed. httpx reports a refused connection as ``All connection attempts
    failed``, keeping the ``RuleSocketConnectionRefusedError`` only in an
    ``ExceptionGroup`` under ``__context__`` -- and plain pickle drops
    ``__cause__``, ``__context__`` and the members of a group, so nothing of it
    survives the transport. A caller then cannot tell a rule from an outage,
    which is the one thing a sandbox has to be able to say.

    The framework recognises its own refusals, so it collects them on the way
    out instead of asking the caller to reconstruct a third party's exception
    tree. Read them back with :func:`sandbox_denials`.

    Args:
        exception: The exception leaving the sandbox. Left untouched if no
            sandbox denial appears in its chain.
    """
    denials = [f"{type(e).__name__}: {e}" for e in _walk_chain(exception) if isinstance(e, SandBoxError)]
    if denials:
        setattr(exception, _DENIALS_ATTRIBUTE, denials)


def sandbox_denials(exception: BaseException) -> list[str]:
    """Return the sandbox denials that caused ``exception``, innermost first.

    Args:
        exception: An exception raised by sandboxed code.

    Works in both usage modes. In partial mode the exception crossed the
    transport, which recorded the denials on the way out because pickle would
    have dropped the chain carrying them; in complete mode nothing crossed
    anything, so the chain is still intact and gets walked here.

    Returns:
        One entry per denial, ``"<ExceptionName>: <message>"``. Empty when the
        failure was not a sandbox refusal, so a caller can tell a rule from an
        ordinary error:

        ```python
        try:
            fetch(url)
        except Exception as e:
            if sandbox_denials(e):
                ...  # a rule refused it
        ```
    """
    recorded = getattr(exception, _DENIALS_ATTRIBUTE, None)
    if isinstance(recorded, list):
        return list(recorded)
    return [f"{type(e).__name__}: {e}" for e in _walk_chain(exception) if isinstance(e, SandBoxError)]


def _walk_chain(exception: BaseException) -> list[BaseException]:
    """Flatten an exception chain, entering the members of every group."""
    found: list[BaseException] = []
    seen: set[int] = set()

    def visit(current: BaseException | None) -> None:
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            found.append(current)
            if isinstance(current, BaseExceptionGroup):
                for member in current.exceptions:
                    visit(member)
            current = current.__cause__ or current.__context__

    visit(exception)
    return found
