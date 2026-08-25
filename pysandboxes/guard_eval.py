# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Guard for code that arrives as a string at runtime.

`builtins.eval`, `builtins.exec` and `builtins.compile` are patched here. A
guarded call parses the source, validates it against the sub-language the
`eval-*` rules describe, rewrites it so the remaining risks are enforced by
`eval_runtime`, and runs it in a dedicated thread under a budget and a
timeout the caller can recover from.

Two deviations from the design spec are recorded here so a later reader does
not "restore" them:

- `SENSITIVE_API["dynamic-code"]` holds three names, not the six of spec 11.
  `builtins.__import__` belongs to `guard_import`, which has its own rules;
  `code.compile_command` and `code.InteractiveInterpreter.runsource` reach the
  three builtins anyway and patching them would double-count one call.
- Spec 8.1 states that CPython's automatic 159-builtin injection is never
  honoured in any mode, and its own table then gives `eval-namespace=caller`
  as honouring it. The bold sentence governs `adaptive` and `closed`; `caller`
  is the debugging escape hatch and does honour injection, warned at load.
"""

import ast
import builtins
import logging
import os
import sys
import threading
import types
from typing import Any, NoReturn, cast

from .e import EvalInterrupted
from .eval_rules import EvalProfiles, EvalRules
from .eval_runtime import HELPERS, EvalState, pop_state, push_state
from .eval_transform import inject, raise_if_rejected, validate
from .immutable_dict import ImmutableDict
from .learning import is_learning_mode

logger = logging.getLogger(__name__)

CAPABILITY_BUILTINS = frozenset(
    {
        "getattr",
        "setattr",
        "open",
        "eval",
        "exec",
        "compile",
        "__import__",
        "type",
        "vars",
        "globals",
        "dir",
        "breakpoint",
    }
)
"""Builtins that reopen by name a door the bounded namespace had shut."""

STRONG_MODULES = frozenset({"os", "subprocess", "importlib", "ctypes", "socket", "posix", "nt", "_socket"})
"""Modules whose callables hand over the host.

Implementation modules are named alongside the facades a reader would write,
because `__module__` reports where a callable was defined, not where it is
reached. Measured on this interpreter: `os.listdir` and `os.system` report
`posix`, so `os` alone would grade them weak. `subprocess`, `importlib`,
`ctypes` and `socket` all report their facade and need no such twin. `nt` is
the Windows counterpart of `posix`, untested here. `_socket` is listed
because `_socket.socket` is a distinct object from `socket.socket` and
reports `_socket`; the facade class itself reports `socket`.
"""

# Matched on the name alone, deliberately, after two narrower tests failed:
#
# - `__module__` cannot qualify it. `open.__module__` is `_io`, not
#   `builtins`, so requiring the latter dropped the most dangerous entry of
#   the whole list.
# - Identity cannot either. The other guards patch `builtins.open` when they
#   arm, so any object captured here at import time stops being the one a
#   caller can pass once the sandbox is active. A guard must not key its
#   classification on the identity of objects another guard replaces.
#
# The cost is an application function of its own called `open` or `type`
# graded strong rather than weak. That is a message wording, not a hole: weak
# findings are reported too, so the name test over-warns where the narrower
# ones went silent.

_SCALARS = (int, float, complex, str, bytes, bool, type(None))
_CONTAINERS = (list, tuple, set, frozenset, dict)

_warned: set[tuple[str, str]] = set()


def _reset_context_warnings() -> None:
    """Clear the deduplication set. Test hook only."""
    _warned.clear()


def classify_context_value(value: Any) -> str:
    """Grade one name a caller put in an eval context.

    Returns:
        `"strong"` when the value grants what the guard closes elsewhere,
        `"weak"` when it runs code the application chose, `""` for data.
    """
    if isinstance(value, types.ModuleType):
        return "strong"
    if callable(value):
        if getattr(value, "__name__", "") in CAPABILITY_BUILTINS:
            return "strong"
        module = getattr(value, "__module__", "") or ""
        if module.partition(".")[0] in STRONG_MODULES:
            return "strong"
        return "weak"
    if isinstance(value, _SCALARS):
        return ""
    if isinstance(value, _CONTAINERS):
        items = value.values() if isinstance(value, dict) else value
        return "" if all(isinstance(item, _SCALARS) for item in items) else "weak"
    return "weak"


_GRADE_HELP = {
    "strong": "the evaluated code can reach everything it exposes",
    "weak": "it runs code outside the sub-language",
}


def warn_about_context(context: dict[str, Any], source_ref: str) -> None:
    """Log one finding per graded name, once per call site.

    `logger.warning`, not `warnings.warn`: every other guard in the package
    reports on the module logger, and a lone `warnings` channel here would be
    the one finding a host's existing logging configuration never saw.

    The deduplication set is kept here because a logger offers no equivalent of
    the `warnings` "once" filter, and the call site is named *in the message*
    because a log record is attributed to the frame that emitted it -- there is
    no `stacklevel` to point it at the application's own `eval()` line.

    Args:
        context: The caller-supplied globals.
        source_ref: Where the call sits, e.g. `tools.py:66`.
    """
    for name, value in context.items():
        if name == "__builtins__":
            continue
        grade = classify_context_value(value)
        if not grade:
            continue
        key = (source_ref, name)
        if key in _warned:
            continue
        _warned.add(key)
        kind = "module" if isinstance(value, types.ModuleType) else "value"
        logger.warning(
            "eval() context provides %s %r at %s\n    %s\n    acknowledge with: eval-call=%s"
            "        (or use eval-namespace=closed)",
            kind,
            name,
            source_ref,
            _GRADE_HELP[grade],
            name,
        )


def _builtins_from(rules: EvalRules) -> dict[str, Any]:
    """Build `__builtins__` from `eval-call`, and from nothing else.

    An empty result is legal and coherent: CPython does not repopulate a
    `__builtins__` key that is present but empty, so a call-free profile
    evaluates arithmetic and comparison over the data the wrapper passed in --
    exactly the calculator the samples ship.

    `builtins` is reached through the module-level import rather than a local
    one: a deferred import runs after arming and is charged to the user's own
    `python-import` rules, which a guard building its namespace must not be.
    """
    allowed = {}
    for name in dir(builtins):
        if rules.call.allows(name):
            allowed[name] = getattr(builtins, name)
    for name in rules.call.allow:
        if name not in allowed and hasattr(builtins, name):
            allowed[name] = getattr(builtins, name)
    return allowed


def build_namespace(
    rules: EvalRules,
    *,
    caller_globals: dict[str, Any] | None,
    names: dict[str, Any] | None,
    from_wrapper: bool,
) -> dict[str, Any]:
    """Return the globals the evaluated code will see.

    Implements the five rows of spec 8.1. The dividing line for the patched
    builtin is `caller_globals is None`, not "arguments were passed":
    `eval(e, None, {"x": 1})` still runs against the caller's module globals,
    so only the first parameter decides.

    `eval-namespace=caller` never reaches here. It is a wrapper-level
    decision: the call goes straight to the raw builtin, because a namespace
    that honours CPython's injection must also skip the rewrite -- injected
    `__sb_getattr__` calls into a namespace that does not carry the helpers
    would raise `NameError` on the first attribute read.

    Args:
        rules: The resolved profile.
        caller_globals: What the application passed as `eval`'s second
            argument, or None.
        names: Wrapper-supplied data, merged in. `guarded_eval` only.
        from_wrapper: The call came through `guarded_eval`, which is itself a
            statement of intent and never takes the adaptive branch.

    Returns:
        The globals mapping. Under the honoured-context rows this is the
        caller's own dict, mutated in place with a `__builtins__` key when it
        had none.
    """
    if not from_wrapper and caller_globals is not None:
        if rules.namespace == "adaptive":
            if "__builtins__" not in caller_globals:
                caller_globals["__builtins__"] = _builtins_from(rules)
            caller_globals.update(HELPERS)
            return caller_globals
    namespace: dict[str, Any] = {"__builtins__": _builtins_from(rules)}
    namespace.update(HELPERS)
    if names:
        namespace.update(names)
    return namespace


TAG_PREFIX = "<eval:"
"""Filename prefix guarded `compile` stamps, and guarded `exec` requires."""

_JOIN_GRACE = 0.5
"""Seconds given to a worker to notice its flag before it is called leaked."""

_profiles: EvalProfiles = ImmutableDict({})
_leaked: int = 0
_leak_lock = threading.Lock()


def activate_guard(profiles: EvalProfiles, *, learn: bool = False) -> None:
    """Install the parsed profiles, just like the other guards.

    Args:
        profiles: The parsed `eval-*` profiles, keyed by profile name.
        learn: Accepted for symmetry with the other guards' signatures but not
            stored: `learning.is_learning_mode()` is the single source of
            truth, the same one `add_learning_rule` consults. A local copy that
            drifted from it would make `run_guarded` record instead of refuse
            while `add_learning_rule` silently dropped everything.
    """
    global _profiles
    del learn
    _profiles = profiles
    logger.debug("guard_eval: %d profile(s)", len(profiles))


def leaked_threads() -> int:
    """Return how many uncooperative workers are still burning CPU."""
    return _leaked


def resolve_profile(profile: str) -> EvalRules:
    """Return the rules for `profile`.

    Args:
        profile: The profile name, `""` for the default one.

    Returns:
        The resolved rules.

    Raises:
        ValueError: The profile is named in the call but absent from the
            configuration. A silent fallback to the default would hand model
            output the wider rule set the call site was trying to avoid.
    """
    rules = _profiles.get(profile)
    if rules is None:
        raise ValueError(f"unknown eval profile {profile!r}, configured: {sorted(_profiles) or ['(none)']}")
    return rules


def _worker(code: Any, mode: str, namespace: dict[str, Any], state: EvalState, box: dict[str, Any]) -> None:
    """Run the compiled code on the worker thread, relaying its outcome."""
    push_state(state)
    try:
        if mode == "eval":
            box["result"] = eval(code, namespace)  # noqa: S307 - guarded source, bounded namespace
        else:
            exec(code, namespace)  # noqa: S102 - guarded source, bounded namespace
    except BaseException as err:  # noqa: BLE001 - relayed verbatim to the caller
        box["error"] = err
    finally:
        pop_state()


def _reraise_from_worker(err: BaseException) -> NoReturn:
    """Re-raise a worker's exception so the traceback reads as one thread.

    Annotated `NoReturn`, not `None`: mypy accepts either here, but `NoReturn`
    states that the call in `run_guarded` is terminal, so a reader does not
    have to check whether execution can fall through to the `return` below it.

    The exception crosses a thread boundary carrying the worker's own
    traceback, whose first entry is `_worker` -- an implementation frame the
    caller has no use for and did not write. Dropping that one entry leaves the
    evaluated source as the innermost frame, which is what a caller expects
    from a call that looks synchronous.

    What deliberately stays: this frame and the `run_guarded` frame the raise
    adds, because both belong to the calling thread's own stack, and the
    `<eval:...>` frames,
    because they are the point of the whole design -- `compile` stamped that
    name so a traceback from evaluated code names the profile it ran under.

    `EvalInterrupted` travels the same path, so a timeout also points at the
    line the source was executing when the watchdog fired.

    Args:
        err: The exception the worker caught.

    Raises:
        BaseException: `err` itself, with the `_worker` frame elided.
    """
    traceback = err.__traceback__
    raise err.with_traceback(traceback.tb_next if traceback is not None and traceback.tb_next else traceback)


def _interrupt(state: EvalState, timeout: float) -> None:
    """Flip the shared state from the watchdog thread.

    `EvalState` is a plain object, never a `threading.local()` belonging to
    the worker: the watchdog must be able to write it, and a thread-local
    would fail silently -- the caller would get its exception while the worker
    ran forever.

    Args:
        state: The budget object the worker's helpers read on every tick.
        timeout: The elapsed budget, named in the refusal message.
    """
    state.interrupted = True
    state.reason = f"eval-timeout={timeout}s"


def run_guarded(
    source: str,
    rules: EvalRules,
    *,
    mode: str,
    namespace: dict[str, Any],
    source_ref: str,
) -> Any:
    """Validate, rewrite, and run `source` under the profile's budgets.

    Args:
        source: The evaluated source.
        rules: The resolved profile.
        mode: `"eval"` or `"exec"`.
        namespace: What `build_namespace` returned.
        source_ref: How the source is named in tracebacks.

    Returns:
        The value of the expression for `"eval"`, None for `"exec"`.

    Raises:
        SyntaxError: The source does not parse; propagated as CPython raised it.
        EvalSyntaxRejected: The source leaves the sub-language.
        EvalInterrupted: A budget or the timeout ran out.
        Exception: Whatever the evaluated code itself raised.
    """
    # `global` is a function-scope directive: reading `_leaked` before
    # declaring it is a SyntaxError, so the declaration comes first.
    global _leaked
    learn = is_learning_mode()
    if _leaked >= rules.max_leaked_threads:
        raise EvalInterrupted(
            f"eval-max-leaked-threads={rules.max_leaked_threads} reached: "
            "earlier evaluations blocked in a C call and are still running"
        )
    tree = ast.parse(source, filename=source_ref, mode=mode)
    state = EvalState(rules, learn=learn)
    violations = validate(tree, rules)
    if learn:
        for violation in violations:
            logger.debug("guard_eval learn: %s", violation.message)
    else:
        raise_if_rejected(source_ref, source, violations)
    # `inject` is typed `ast.AST` because it transforms any node; what comes
    # back here is whatever `ast.parse` built for `mode` -- a `Module` for
    # "exec", an `Expression` for "eval" -- and `compile` accepts either.
    code = compile(cast("ast.Module | ast.Expression", inject(tree)), source_ref, mode)
    box: dict[str, Any] = {}
    worker = threading.Thread(
        target=_worker,
        args=(code, mode, namespace, state, box),
        name=f"guard_eval{source_ref}",
        daemon=True,
    )
    watchdog = threading.Timer(rules.timeout, _interrupt, args=(state, rules.timeout))
    watchdog.start()
    worker.start()
    worker.join(rules.timeout + _JOIN_GRACE)
    watchdog.cancel()
    if worker.is_alive():
        # A blocking C call never returns to a tick. The caller gets its
        # exception; the thread keeps burning CPU, cumulatively across calls.
        # The real guarantee is the OS layer, where a timeout is a process
        # kill. Documented as a limit, not presented as covered.
        with _leak_lock:
            _leaked += 1
        logger.warning("guard_eval: %s did not stop; %d leaked thread(s)", source_ref, _leaked)
        raise EvalInterrupted(f"eval-timeout={rules.timeout}s exhausted, and the worker did not stop")
    if "error" in box:
        _reraise_from_worker(box["error"])
    return box.get("result")


def guarded_eval(
    source: str,
    *,
    profile: str = "",
    names: dict[str, Any] | None = None,
    mode: str = "eval",
) -> Any:
    """Evaluate `source` under a declared sub-language.

    Choosing this entry point over the patched builtin is itself the statement
    of intent, which is why `eval-namespace` does not apply to it: `names` is
    wrapper-supplied data merged into a namespace built from `eval-call`,
    never used in place of one.

    Args:
        source: The code to evaluate.
        profile: Which `eval-*` profile to apply, `""` for the default one.
        names: Data bound into the namespace.
        mode: `"eval"` for an expression, `"exec"` for statements.

    Returns:
        The value of the expression, or None in `"exec"` mode.

    Raises:
        ValueError: `profile` is not configured.
        EvalSyntaxRejected: The source leaves the sub-language.
        EvalInterrupted: A budget or the timeout ran out. Note that this does
            **not** derive from `SandBoxError`, so `except SandBoxError:` will
            not catch it.
    """
    rules = resolve_profile(profile)
    source_ref = f"{TAG_PREFIX}{profile or 'default'}>"
    namespace = build_namespace(rules, caller_globals=None, names=names, from_wrapper=True)
    return run_guarded(source, rules, mode=mode, namespace=namespace, source_ref=source_ref)


if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:

    def _deactivate_guard_eval() -> None:
        """Reset the guard between tests."""
        global _profiles, _leaked
        _profiles = ImmutableDict({})
        _leaked = 0
        _reset_context_warnings()
