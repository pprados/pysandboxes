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

import logging
import operator
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


def __sb_getattr__(obj: Any, name: str) -> Any:
    """Return `obj.name` when the rules allow that name.

    Args:
        obj: The object the source wrote to the left of the dot.
        name: The attribute name, as written.

    Returns:
        The attribute value.

    Raises:
        RuleEvalPermissionError: The name is a frame-capture attribute, an
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
    else:
        if not state.rules.attribute.allows(name):
            state.attributes.add(name)
            if not state.learn:
                raise RuleEvalPermissionError(name, "eval-attribute")
    return getattr(obj, name)


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
    "__sb_getattr__": __sb_getattr__,
    "__sb_binop__": __sb_binop__,
    "__sb_iter__": __sb_iter__,
}
"""The names bound into every guarded namespace, none reachable via eval-call."""
