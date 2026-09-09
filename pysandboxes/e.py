# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Exception classes for PySandboxes.

This module centralizes all exception types to provide better stack traces
and consistent error handling throughout the framework.
"""

from pickle import UnpicklingError


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
    """Raised when a path is not exposed to the sandbox, or is hidden from it.

    Two rules end here: no `expose-ro=` or `expose-rw=` covers the path, or an
    `ignore=` rule hides it deliberately. ``errno`` is set to ``ENOENT`` so
    code that only knows how to handle a missing file keeps working -- the
    sandbox says "not there" rather than "not allowed", which is also what
    keeps the file system layout from leaking.

    Expose the path with `expose-ro=<path>`, or `expose-rw=<path>` if the code
    also writes to it.
    """


class RulePermissionError(PermissionError, SandBoxError):
    """Raised when the sandbox writes to a path it may only read.

    The path is exposed, so it is visible and readable, but the rule covering
    it grants no write access. Distinct from `RuleFileNotFoundError`, which
    means the path is not exposed at all.

    Replace the `expose-ro=<path>` rule with `expose-rw=<path>`.
    """


class RuleSocketConnectionRefusedError(ConnectionRefusedError, SandBoxError):
    """Raised when a network connection is not allowed to the sandbox.

    Covers every stage the socket guard checks -- name resolution, connect,
    and the address family itself -- so a refusal reaches the caller as an
    ordinary refused connection.

    Allow the destination with `net=<host>:<port>`.
    """


class RuleModuleNotFoundError(ModuleNotFoundError, SandBoxError):
    """Raised when an import is not allowed to the sandbox.

    Every import is refused unless a rule names the module, so this reaches
    the caller as a plain missing module. It says nothing about whether the
    module is installed.

    Allow it with `python-import=ALLOW:<module>`.
    """


class RuleAttributeError(AttributeError, SandBoxError):
    """Refusal to write an attribute the framework protects on its own modules.

    Reserved for the self-protection guard: the guards run inside the process
    they protect, so rewriting one of their module attributes would disarm the
    sandbox from inside. That guard is not active today -- `guard_self`
    installs nothing -- so nothing raises this at present. It stays public
    because a caller catching `SandBoxError` must keep working once it does.
    """


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


class EvalSyntaxRejected(SandBoxError, SyntaxError):
    """Raised when a dynamically evaluated source violates the eval rules.

    Carries the full violation list rather than the first refusal: a model
    correcting its own output converges in one round only if it is told
    everything at once.

    Deriving from `SyntaxError` as well as `SandBoxError` is deliberate and
    verified free of instance lay-out conflict: editors and tracebacks already
    know how to render `lineno`, `offset` and `text`.
    """

    def __init__(
        self,
        message: str,
        violations: list[str],
        *,
        lineno: int = 0,
        offset: int = 0,
        text: str = "",
    ) -> None:
        """Initialize the exception with the full report.

        Args:
            message: Headline naming how many rules were violated and where.
            violations: One rendered block per violation, in source order.
            lineno: Line of the first violation, for `SyntaxError` consumers.
            offset: Column of the first violation.
            text: Source line the first violation sits on.
        """
        report = message + "\n\n" + "\n".join(violations)
        super().__init__(report)
        # `msg` is assigned explicitly because `super().__init__` never reaches
        # `SyntaxError.__init__`: the MRO runs through `RuntimeError`, whose
        # initializer is `BaseException`'s and only fills `args`. `msg` would
        # stay None, and `SyntaxError.__str__` -- which is the `__str__` this
        # class inherits -- would render the whole report as "None (line N)",
        # hiding from `str(err)` the very violations the class exists to carry.
        self.msg = report
        self.violations = violations
        self.lineno = lineno
        self.offset = offset
        self.text = text

    def __reduce__(self) -> tuple[type, tuple[str, list[str]]]:
        """Rebuild the exception from its own attributes across the transport."""
        return self.__class__, (str(self).split("\n\n", maxsplit=1)[0], self.violations)


class EvalInterrupted(BaseException):
    """Raised inside evaluated code when a budget or the timeout is exhausted.

    The one exception of the framework that stays outside the `SandBoxError`
    hierarchy, and the exclusion is load-bearing: `SandBoxError` derives from
    `RuntimeError`, so a bare `except Exception:` inside the evaluated source
    -- reachable as soon as `eval-syntax=exception` opens `Try` -- would
    swallow its own interruption. Deriving from `BaseException` alone keeps the
    interruption uncatchable from inside.

    Consequence for callers: `except SandBoxError:` does not catch a timeout.
    """

    def __init__(self, reason: str) -> None:
        """Initialize the interruption with the exhausted budget.

        Args:
            reason: The rule and value that ran out, e.g. `eval-timeout=5s`.
        """
        super().__init__(f"evaluation interrupted: {reason}")
        self.reason = reason

    def __reduce__(self) -> tuple[type, tuple[str]]:
        """Rebuild the interruption from its own attributes."""
        return self.__class__, (self.reason,)


class RuleEvalPermissionError(PermissionError, SandBoxError):
    """Raised when a runtime guard refuses an attribute or an allocation."""

    def __init__(self, target: str, rule_key: str, hint: str | None = None) -> None:
        """Initialize the exception with the refused name and its rule key.

        Args:
            target: Attribute name, or a description of the refused operation.
            rule_key: Configuration key that would allow it, e.g. `eval-magic`.
            hint: Replaces the "add this rule" sentence. Set it whenever no
                configuration can lift the refusal, so a message from a
                security guard never tells the reader to add a key that will
                not work -- which reads as a broken guard rather than as a
                deliberate, non-overridable denial.
        """
        remedy = hint or f"Add `{rule_key}={target}` to allow it."
        super().__init__(f"{target!r} is denied by the eval guard.\n{remedy}")
        self.target = target
        self.rule_key = rule_key
        self.hint = hint

    def __reduce__(self) -> tuple[type, tuple[str, str, str | None]]:
        """Rebuild the exception from its own attributes across the transport."""
        return self.__class__, (self.target, self.rule_key, self.hint)


class RestrictedUnpicklingError(UnpicklingError, SandBoxError):
    """Raised when the SSE transport refuses to deserialize a child->parent payload.

    The result and exception channels carry data the sandboxed child produced,
    so the parent unpickles them through a restricted unpickler: an opcode
    outside the allowlist, a resolved callable the site's predicate refuses, an
    import the stream would trigger, or a size budget can each raise this. It
    derives from `UnpicklingError` so a caller treating it as a pickle failure
    still catches it, and from `SandBoxError` so `except SandBoxError` does too.

    See wiki/audit-python-security.md.
    """


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
        set_sandbox_denials(exception, denials)


def set_sandbox_denials(exception: BaseException, denials: list[str]) -> None:
    """Record ``denials`` on ``exception`` verbatim.

    Used when the denials are already known rather than walked out of a chain:
    the transport carries them as strings, and the exception the parent rebuilds
    has no chain left to walk.

    Args:
        exception: The exception to annotate.
        denials: One entry per denial, as :func:`sandbox_denials` returns them.
    """
    setattr(exception, _DENIALS_ATTRIBUTE, list(denials))


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
