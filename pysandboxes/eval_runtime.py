# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Runtime helpers the injected code calls.

These are the *barrier* of the design. Static validation inspects names as
they are written in the source and is trivially bypassable -- a dynamically
built dunder is never seen by it -- so the enforcement that actually holds
lives here and in the bounded namespace. Do not optimise these away later on
the grounds that `eval-magic` already exists.

Every helper keeps a trailing double underscore: Python mangles `__name`
inside a class body but leaves `__name__` alone, and `eval-syntax=class`
puts evaluated code inside class bodies.
"""

import _string  # pyright: ignore[reportMissingImports]  # C module; provides formatter_field_name_split
import logging
import operator
import re
import string
import threading
from typing import Any, Callable, Iterator

from .e import EvalInterrupted, RuleEvalPermissionError
from .eval_rules import EvalRules

logger = logging.getLogger(__name__)

# Attributes that hand back a real frame or code object, and through it the
# unguarded globals of the calling program. Refused even when eval-attribute
# would allow them: a generator reaches the real globals through
# gi_frame.f_globals without writing a single dunder, so no configuration --
# not even `eval-attribute=*` -- should be able to open that by accident. The
# one implicit, non-overridable DENY of the design; deliberate, finite, and
# enumerated here.
FRAME_CAPTURE = frozenset(
    {
        "gi_frame",
        "gi_code",
        "gi_yieldfrom",
        "cr_frame",
        "cr_code",
        "cr_await",
        "ag_frame",
        "ag_code",
        "f_globals",
        "f_locals",
        "f_builtins",
        "f_back",
        "f_trace",
        "tb_frame",
        "tb_next",
    }
)

# Naming a rule key here would send the reader after a line that changes
# nothing, since this denial is the one no configuration lifts.
_FRAME_CAPTURE_HINT = "Frame capture is always refused; no eval- rule grants it."

_SEQUENCES = (str, bytes, bytearray, list, tuple)

_BINOPS: dict[str, Callable[[Any, Any], Any]] = {
    "+": operator.add,
    "*": operator.mul,
    "**": operator.pow,
}


class EvalState:
    """Budgets and observations for one evaluation.

    A plain object, never a `threading.local()`: the watchdog thread must be
    able to set `interrupted`, and a thread-local belonging to the worker is
    not writable from outside it. The worker reaches this object through a
    thread-local *pointer*; the watchdog holds a direct reference.

    Attributes:
        rules: The profile in force for this evaluation.
        learn: Record refusals instead of raising them.
        interrupted: Set by the watchdog; the next tick raises.
        reason: The budget that ran out, for the `EvalInterrupted` message.
        iterations: Loop and comprehension iterations consumed so far.
        depth: Current runtime call depth of evaluated functions.
        attributes: Ordinary attribute names observed, for learning mode.
        magic: Dunder names observed, for learning mode.
    """

    __slots__ = ("rules", "learn", "interrupted", "reason", "iterations", "depth", "attributes", "magic")

    def __init__(self, rules: EvalRules, *, learn: bool = False) -> None:
        """Initialize a fresh budget for one evaluation.

        Args:
            rules: The resolved profile.
            learn: Whether to record refusals rather than raise them.
        """
        self.rules = rules
        self.learn = learn
        self.interrupted = False
        self.reason = ""
        self.iterations = 0
        self.depth = 0
        self.attributes: set[str] = set()
        self.magic: set[str] = set()


_current = threading.local()


def push_state(state: EvalState) -> None:
    """Make `state` the one the helpers read on this thread."""
    stack: list[EvalState] = getattr(_current, "stack", [])
    stack.append(state)
    _current.stack = stack


def pop_state() -> EvalState:
    """Drop the innermost state and return it."""
    stack: list[EvalState] = _current.stack
    return stack.pop()


def current_state() -> EvalState:
    """Return the state in force on this thread.

    Raises:
        RuntimeError: No evaluation is in progress, which means injected code
            escaped its execution frame -- a bug, never a user error.
    """
    stack: list[EvalState] = getattr(_current, "stack", [])
    if not stack:
        raise RuntimeError("a __sb_ helper ran outside any guarded evaluation")
    return stack[-1]


def in_evaluation() -> bool:
    """Return whether a guarded evaluation is in progress on this thread."""
    return bool(getattr(_current, "stack", None))


def __sb_tick__() -> None:
    """Charge one iteration and honour an interruption.

    Hot path: an attribute read, a compare and an increment. Ticks sit at loop
    bodies and comprehension iterables, so straight-line code and a lone
    `10**9` consume none -- those are the job of `__sb_binop__` and the
    timeout.
    """
    state = current_state()
    if state.interrupted:
        raise EvalInterrupted(state.reason)
    state.iterations += 1
    if state.iterations > state.rules.max_iterations:
        state.interrupted = True
        state.reason = f"eval-max-iterations={state.rules.max_iterations}"
        raise EvalInterrupted(state.reason)


def __sb_enter__() -> None:
    """Charge one call frame of evaluated code.

    The iteration tick does not bound recursion -- a recursive function
    consumes no iteration -- so without this a runaway recursion would only
    hit CPython's `RecursionError`, which is an `Exception` and therefore
    catchable by the evaluated code itself once `eval-syntax=exception` opens
    `Try`.
    """
    state = current_state()
    if state.interrupted:
        raise EvalInterrupted(state.reason)
    if state.depth >= state.rules.max_call_depth:
        state.interrupted = True
        state.reason = f"eval-max-call-depth={state.rules.max_call_depth}"
        raise EvalInterrupted(state.reason)
    state.depth += 1


def __sb_leave__() -> None:
    """Release one call frame. Injected in a `finally`, so it always runs."""
    state = current_state()
    state.depth = max(0, state.depth - 1)


def __sb_func__(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Bracket a lambda's every call with `__sb_enter__`/`__sb_leave__`.

    A `FunctionDef` body is rewritten with an inline enter/try/finally-leave;
    a lambda body is a single expression that admits no statement, so the
    lambda object is wrapped instead. Without this, lambda recursion consumes
    no call frame and is bounded only by CPython's `RecursionError`, which the
    evaluated code can catch once `eval-syntax=exception` is granted.
    """

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        __sb_enter__()
        try:
            return fn(*args, **kwargs)
        finally:
            __sb_leave__()

    return wrapper


def _attr_allowed(name: str) -> bool:
    """Return whether `name` would pass the attribute rules, silently.

    A pure predicate for `dir()` filtering: it neither records an observation
    for learning nor raises. `_check_attr` is the enforcing counterpart.
    """
    if name in FRAME_CAPTURE:
        return False
    rules = current_state().rules
    if name.startswith("__") and name.endswith("__"):
        return rules.magic.allows(name)
    return rules.attribute.allows(name)


def _check_attr(name: str) -> None:
    """Enforce the attribute rules for `name`, recording it in learning mode.

    The single gate every attribute read passes through, whatever its syntax:
    the injected `__sb_getattr__`, the `getattr`/`vars`/`hasattr` builtin
    shims, and the `str.format` field walk all call it, so a name can no
    longer reach the object through a path the dotted form would refuse.

    Raises:
        RuleEvalPermissionError: `name` is a frame-capture attribute, an
            undeclared dunder, or an undeclared ordinary name.
    """
    if name in FRAME_CAPTURE:
        raise RuleEvalPermissionError(name, "eval-attribute", _FRAME_CAPTURE_HINT)
    state = current_state()
    if name.startswith("__") and name.endswith("__"):
        if not state.rules.magic.allows(name):
            state.magic.add(name)
            if not state.learn:
                raise RuleEvalPermissionError(name, "eval-magic")
    elif not state.rules.attribute.allows(name):
        state.attributes.add(name)
        if not state.learn:
            raise RuleEvalPermissionError(name, "eval-attribute", _FORMAT_HINT if name in _FORMAT_METHODS else None)


_FORMAT_METHODS = frozenset({"format", "format_map"})

_FORMAT_HINT = (
    'Prefer an f-string (f"{x}"), whose attribute accesses are checked like any other; '
    "or name `eval-attribute=format` (or `format_map`) exactly -- a pattern never grants it."
)


def _validate_format_template(template: str) -> None:
    """Run every attribute access a format template performs past `_check_attr`.

    `str.format` resolves `{0.__class__}` in C from the contents of the
    string, so no `Attribute` node exists for phase 1 or `__sb_getattr__` to
    see. The template is known here -- it is the string the method is bound to
    -- so each field's attribute accesses are validated before the C call.
    Index access (`{0[0]}`) is data and left alone; nested spec fields
    (`{0:{1.__class__}}`) are walked in turn.

    Raises:
        RuleEvalPermissionError: A field reaches a refused attribute.
    """
    for _literal, field, spec, _conversion in string.Formatter().parse(template):
        if field is not None:
            check_format_field(field)
        if spec and "{" in spec:
            _validate_format_template(spec)


def check_format_field(field: str) -> None:
    """Run the attribute accesses of one format field (`0.a.b`) past `_check_attr`.

    Raises:
        RuleEvalPermissionError: The field reaches a refused attribute.
    """
    _first, rest = _string.formatter_field_name_split(field)
    for is_attribute, value in rest:
        if is_attribute:
            _check_attr(value)


def _guarded_format(template: str, name: str) -> Callable[..., str]:
    """Return a bound `str.format`/`format_map` that validates its template."""

    def bound(*args: Any, **kwargs: Any) -> str:
        _validate_format_template(template)
        return getattr(template, name)(*args, **kwargs)  # type: ignore[no-any-return]

    return bound


def _guarded_format_unbound(cls: type, name: str) -> Callable[..., str]:
    """Return an unbound `str.format`/`format_map` that validates arg zero.

    `str.format(template, ...)` and `type('').format(...)` reach the method
    through the class, not an instance, so the template is the first positional
    argument rather than the bound object. Without this the instance guard was
    a side door away: `str.format('{0.__class__}', ())` walked the type
    hierarchy untouched.
    """

    def unbound(template: Any = "", *args: Any, **kwargs: Any) -> str:
        if isinstance(template, str):
            _validate_format_template(template)
        return getattr(cls, name)(template, *args, **kwargs)  # type: ignore[no-any-return]

    return unbound


def __sb_getattr__(obj: Any, name: str) -> Any:
    """Return `obj.name` when the rules allow that name.

    Args:
        obj: The object the source wrote to the left of the dot.
        name: The attribute name, as written.

    Returns:
        The attribute value, or a validating wrapper for `str.format`.

    Raises:
        RuleEvalPermissionError: The name is a frame-capture attribute, an
            undeclared dunder, or an undeclared ordinary name.
    """
    _check_attr(name)
    if name in _FORMAT_METHODS:
        if isinstance(obj, str):
            return _guarded_format(obj, name)
        if isinstance(obj, type) and issubclass(obj, str):
            return _guarded_format_unbound(obj, name)
    _warn_about_regex(obj, name)
    value = getattr(obj, name)
    if callable(value) and (
        isinstance(obj, string.Formatter) or (isinstance(obj, type) and issubclass(obj, string.Formatter))
    ):
        return _carry_state(value)
    return value


def _carry_state(method: Callable[..., Any]) -> Callable[..., Any]:
    """Return `method` bound to the evaluation that fetched it, on any thread.

    The patched `string.Formatter.get_field` checks fields only while an
    evaluation state sits on the current thread. Handed to an executor the
    application supplied, a `Formatter` method would run on a thread with no
    state and read `{0.__class__}` unchecked; this wrapper pushes the fetching
    evaluation's state there for the duration of the call.
    """
    state = current_state()

    def carried(*args: Any, **kwargs: Any) -> Any:
        if in_evaluation():
            return method(*args, **kwargs)
        push_state(state)
        try:
            return method(*args, **kwargs)
        finally:
            pop_state()

    return carried


_MISSING = object()


def __sb_b_getattr__(obj: Any, name: str, *default: Any) -> Any:
    """Guarded `getattr`: the builtin routed through `__sb_getattr__`.

    The raw builtin reads any attribute in C, so binding it unguarded reopened
    `eval-magic`, `eval-attribute` and the frame-capture DENY by name. The
    three-argument default is honoured only after the name itself is allowed.
    """
    try:
        return __sb_getattr__(obj, name)
    except AttributeError:
        if default:
            return default[0]
        raise


def __sb_b_hasattr__(obj: Any, name: str) -> bool:
    """Guarded `hasattr`: probing existence still passes the attribute rules."""
    try:
        __sb_getattr__(obj, name)
        return True
    except AttributeError:
        return False


def __sb_b_vars__(obj: Any = _MISSING) -> Any:
    """Guarded `vars`: `__dict__` handed raw is the whole attribute surface.

    Routed through `__sb_getattr__(obj, "__dict__")`, so it is gated by
    `eval-magic=__dict__`. The no-argument form returns the caller's locals --
    here the evaluation frame -- and is refused outright.
    """
    if obj is _MISSING:
        raise RuleEvalPermissionError("vars", "eval-call", "vars() with no argument exposes the evaluation frame")
    return __sb_getattr__(obj, "__dict__")


def __sb_b_setattr__(*_args: Any, **_kwargs: Any) -> Any:
    """Guarded `setattr`: attribute store is refused, as it is for the dot."""
    raise RuleEvalPermissionError("setattr", "eval-attribute", "the sub-language does not mutate attributes")


def __sb_b_delattr__(*_args: Any, **_kwargs: Any) -> Any:
    """Guarded `delattr`: attribute delete is refused, as it is for the dot."""
    raise RuleEvalPermissionError("delattr", "eval-attribute", "the sub-language does not delete attributes")


def __sb_b_breakpoint__(*_args: Any, **_kwargs: Any) -> Any:
    """Guarded `breakpoint`: the debugger reaches the host and is refused."""
    raise RuleEvalPermissionError("breakpoint", "eval-call", "the debugger is not reachable from the sub-language")


def __sb_b_globals__() -> Any:
    """Guarded `globals`: the evaluation namespace is not handed back."""
    raise RuleEvalPermissionError("globals", "eval-call", "the evaluation namespace is not exposed")


def __sb_b_dir__(obj: Any = _MISSING) -> list[str]:
    """Guarded `dir`: the no-argument form is refused, the rest is filtered.

    `dir()` with no argument lists the evaluation frame's names; `dir(obj)` is
    trimmed to the attributes the rules would let through, so it never becomes
    a catalogue of the refused surface.
    """
    if obj is _MISSING:
        raise RuleEvalPermissionError("dir", "eval-call", "dir() with no argument exposes the evaluation frame")
    return [name for name in dir(obj) if _attr_allowed(name)]


def __sb_b_type__(*args: Any) -> Any:
    """Guarded `type`: the one-argument query is kept, the class factory is not.

    `type(x)` returns a class whose own attributes stay gated by
    `__sb_getattr__`; `type(name, bases, dict)` builds a new class and is
    refused.
    """
    if len(args) == 1:
        return type(args[0])
    raise RuleEvalPermissionError("type", "eval-call", "the three-argument class factory is refused")


GUARDED_BUILTINS: dict[str, Callable[..., Any]] = {
    "getattr": __sb_b_getattr__,
    "hasattr": __sb_b_hasattr__,
    "vars": __sb_b_vars__,
    "setattr": __sb_b_setattr__,
    "delattr": __sb_b_delattr__,
    "breakpoint": __sb_b_breakpoint__,
    "globals": __sb_b_globals__,
    "dir": __sb_b_dir__,
    "type": __sb_b_type__,
}
"""Builtins bound under their own name but replaced by a guarded shim.

`eval-call` grants the name; the namespace binds the shim, so the sensitive
builtin can no longer be the side door the bounded namespace closed. `open`,
`eval`, `exec`, `compile` and `__import__` are absent on purpose: each is
already covered by its own guard (files, this guard re-entered, imports)."""


_REGEX_ENGINE_ATTRS = frozenset(
    {"compile", "match", "search", "fullmatch", "findall", "finditer", "split", "sub", "subn"}
)
"""Attributes of `re` and of a compiled pattern that start the matching engine."""

_warned_regex: set[str] = set()


def _reset_regex_warnings() -> None:
    """Clear the deduplication set. Test hook only."""
    _warned_regex.clear()


def _warn_about_regex(obj: Any, name: str) -> None:
    """Report one reach into the backtracking engine, once per attribute name.

    A finding, never a refusal: whether a pattern needs `re` is the application's
    call, and this guard cannot make it. What it can do is say that the budget
    the profile declares does not apply here.

    `__sb_tick__` bounds the evaluated code by polling a flag the rewrite injects
    at loop bodies. A match is one opaque C call: it charges no tick, and it does
    not release the GIL. So `(a+)+` on a 28-character subject runs for seconds
    with the watchdog unable to observe anything, `run_guarded` gives up on the
    join, and the worker keeps the whole interpreter -- the host application
    included -- while it finishes. Measured growth is a factor of four per two
    added characters, so bounding the subject is not a fix either.

    Identity, not the name: a caller who followed the advice and passed a linear
    engine under the name `re` must stop being told to follow it.
    """
    if name not in _REGEX_ENGINE_ATTRS:
        return
    if obj is not re and not isinstance(obj, re.Pattern):
        return
    if name in _warned_regex:
        return
    _warned_regex.add(name)
    logger.warning(
        "eval() reached re.%s, whose engine backtracks: a pattern such as (a+)+ runs past"
        " eval-timeout and holds the GIL, because a match charges no tick.\n"
        "    prefer a linear engine, injected by the application:"
        ' eval(expr, {"re": re2})   (pip install google-re2)\n'
        "    re2 refuses lookaround and backreferences, which is the price of the guarantee",
        name,
    )


def _refuse_alloc(detail: str) -> None:
    raise RuleEvalPermissionError(detail, "eval-max-alloc")


def __sb_binop__(op: str, left: Any, right: Any) -> Any:
    """Apply `op` after checking what it is about to allocate.

    `10 ** 10**9` hangs CPython inside C with no way back, and `[0] * 10**10`
    allocates before any tick can fire, so both are checked before the
    operation rather than interrupted during it.

    Args:
        op: One of `+`, `*`, `**`; the injector rewrites no other operator.
        left: Left operand.
        right: Right operand.

    Returns:
        The result of the operation.

    Raises:
        RuleEvalPermissionError: The result would exceed `eval-max-alloc`.
    """
    budget = current_state().rules.max_alloc
    if op == "**":
        if isinstance(left, int) and isinstance(right, int) and right > 0 and abs(left) > 1:
            # bit length of the result, without computing it
            if left.bit_length() * right > budget * 8:
                _refuse_alloc(f"{left} ** {right} would allocate more than eval-max-alloc={budget}")
    elif op == "*":
        for sequence, count in ((left, right), (right, left)):
            if isinstance(sequence, _SEQUENCES) and isinstance(count, int) and not isinstance(count, bool):
                if len(sequence) * count > budget:
                    _refuse_alloc(f"a {len(sequence) * count}-element repetition exceeds eval-max-alloc={budget}")
    elif op == "+":
        if isinstance(left, _SEQUENCES) and isinstance(right, _SEQUENCES):
            if len(left) + len(right) > budget:
                _refuse_alloc(f"a {len(left) + len(right)}-element concatenation exceeds eval-max-alloc={budget}")
    return _BINOPS[op](left, right)


def __sb_iter__(iterable: Any) -> Iterator[Any]:
    """Tick once per item, so a comprehension stays interruptible.

    A comprehension accepts no statement, so the tick cannot be injected into
    its body the way a loop's is; wrapping the iterable is the only place left.
    """
    for item in iterable:
        __sb_tick__()
        yield item


HELPERS: dict[str, Any] = {
    "__sb_tick__": __sb_tick__,
    "__sb_enter__": __sb_enter__,
    "__sb_leave__": __sb_leave__,
    "__sb_func__": __sb_func__,
    "__sb_getattr__": __sb_getattr__,
    "__sb_binop__": __sb_binop__,
    "__sb_iter__": __sb_iter__,
}
"""The names bound into every guarded namespace, none reachable via eval-call."""
