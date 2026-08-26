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

What this guard does not cover, stated so no one reads more into it:

- Blocking C calls. Catastrophic backtracking in `re`, a large integer
  operation that slipped past `__sb_binop__`, a native library: none returns
  to a tick, so `join(timeout)` hands the caller its `EvalInterrupted` while
  the thread keeps burning CPU. Mitigated by the leak counter, guaranteed
  only by the OS layer, where a timeout is a process kill.
- Memory outside the rewritten operators. `eval-max-alloc` bounds `+`, `*`
  and `**`, not the process.
- CPython bugs. A segfault or an interpreter escape is out of reach of any
  AST-level guard.
- Side effects of allowed calls. If `eval-call` grants a function that opens
  files, the file rules apply, but this guard adds nothing.
- Timing and side channels.
- `str.format` and `format_map`. The attribute is resolved in C from the
  contents of the string, so no `Attribute` node exists to validate or
  rewrite. Handled by curating them out of `str-methods`, which is a
  mitigation and not a fix: granting `format` by name reopens it, with a
  warning.
- Audit from the configuration alone, under `eval-namespace=adaptive`: the
  reachable surface is the configuration *plus* what each call site passes.
  `eval-namespace=closed` restores the property, at the cost of declaring
  every name.
- Code generation by a third-party library outside `site-packages` -- a
  vendored `attrs`, a source checkout on PYTHONPATH. The ambient exemption is
  path-based, so such a library is guarded like application code and its
  generated `FunctionDef` will be refused. `python-api=ALLOW:dynamic-code` is
  the escape hatch.
"""

import ast
import builtins
import functools
import logging
import os
import sys
import sysconfig
import threading
import types
from pathlib import Path
from typing import Any, Callable, NoReturn, cast

from . import guard_api
from .e import EvalInterrupted, RuleApiPermissionError
from .guard_api import LearnApiRule
from .eval_rules import DEFAULT_RULES, EvalProfiles, EvalRules, LearnEvalContext, LearnEvalRule
from .eval_runtime import HELPERS, EvalState, pop_state, push_state
from .eval_transform import inject, learn_targets, raise_if_rejected, validate
from .immutable_dict import ImmutableDict
from .learning import add_learning_rule, is_learning_mode
from .tools import patch_factory as _f

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

# Captured at import time, before activate_sandboxes installs the patches, so
# these are the unpatched builtins. The guard runs its own source through
# compile/eval/exec, and in a development checkout this file sits outside both
# the stdlib and site-packages, so the ambient exemption does not cover it:
# without the capture the guard hands its own rewritten AST to its own patched
# compile, which refuses it as "a code object the guard did not produce".
_RAW_COMPILE = compile
_RAW_EVAL = eval
_RAW_EXEC = exec

# Same reasoning for the watchdog. Running the source in a watched thread is
# this guard's implementation detail, and guard_api denies
# threading.Thread.start without `python-api=ALLOW:threads`. Charging that to
# the caller would mean an application had to open threading for all of its
# own code just to obtain an eval timeout -- a wider grant than the feature
# it pays for.
_RAW_THREAD_START = threading.Thread.start
_RAW_THREAD_PRIMITIVES = {
    name: getattr(threading, name)
    for name in ("_start_joinable_thread", "_start_new_thread")
    if hasattr(threading, name)
}


def _start_unguarded(thread: threading.Thread) -> None:
    """Start one of the guard's own threads without charging the user's rules.

    Capturing `Thread.start` alone is not enough: its body resolves
    `_start_joinable_thread` as a module global of `threading`, and that name
    is patched too. The captured primitives are swapped back for the duration
    of the call and restored immediately after.

    The window is the start call itself. The worker it launches runs evaluated
    source, which cannot reach `threading`: the namespace is built from
    `eval-call` and carries no import machinery.

    Args:
        thread: The worker or the watchdog.
    """
    patched = {name: getattr(threading, name) for name in _RAW_THREAD_PRIMITIVES}
    for name, raw in _RAW_THREAD_PRIMITIVES.items():
        setattr(threading, name, raw)
    try:
        _RAW_THREAD_START(thread)
    finally:
        for name, value in patched.items():
            setattr(threading, name, value)


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
            box["result"] = _RAW_EVAL(code, namespace)
        else:
            _RAW_EXEC(code, namespace)
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
        for key, name in learn_targets(violations):
            add_learning_rule(LearnEvalRule(key, name))
    else:
        raise_if_rejected(source_ref, source, violations)
    # `inject` is typed `ast.AST` because it transforms any node; what comes
    # back here is whatever `ast.parse` built for `mode` -- a `Module` for
    # "exec", an `Expression` for "eval" -- and `compile` accepts either.
    code = _RAW_COMPILE(cast("ast.Module | ast.Expression", inject(tree)), source_ref, mode)
    box: dict[str, Any] = {}
    worker = threading.Thread(
        target=_worker,
        args=(code, mode, namespace, state, box),
        name=f"guard_eval{source_ref}",
        daemon=True,
    )
    watchdog = threading.Timer(rules.timeout, _interrupt, args=(state, rules.timeout))
    _start_unguarded(watchdog)
    _start_unguarded(worker)
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
    if learn:
        # Recorded after the run, not during validation: these are names the
        # source reached at runtime, which no static pass can enumerate.
        for name in state.attributes:
            add_learning_rule(LearnEvalRule("eval-attribute", name))
        for name in state.magic:
            add_learning_rule(LearnEvalRule("eval-magic", name))
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


_STDLIB_ROOTS = tuple(
    str(Path(path).resolve())
    for path in (sysconfig.get_paths().get("stdlib"), sysconfig.get_paths().get("platstdlib"))
    if path
)
_VENDOR_SEGMENTS = ("site-packages", "dist-packages")


def is_ambient(frame: types.FrameType) -> bool:
    """Return whether this call is the runtime generating its own code.

    Measured on 3.13 for a single `pydantic.BaseModel` definition: 655
    `compile` from `typing`, 116 `exec` from `importlib._bootstrap`, 50 from
    `dataclasses`, 29 from `typing_inspection`, 18 `eval` from `collections`.
    Routing those through phase 1 refuses them -- `dataclasses.__create_fn__`
    builds a `FunctionDef` -- and refusing the `importlib` ones means no
    module can be imported at all. Library code generation is therefore
    exempt, and only the application's own call sites are guarded.

    The discriminator is the caller's code object filename rather than its
    module name: `__name__` is reachable from evaluated code, so
    `eval(src, {"__name__": "dataclasses"})` would spoof a name-based
    allowlist. A filename can only be chosen through `compile()`, which is
    itself guarded and absent from the namespace under `closed`.

    Only `<frozen ...>` is exempt among the angle-bracket names, not every
    name starting with `<`. `python-sb script.py` and `python-sb -c` both run
    the user's code through `exec`, which stamps it `<string>`: exempting that
    would exempt the application itself, which is the one thing this guard
    exists to cover. The stdlib's own generators are reached by the path rule
    below instead -- `dataclasses` builds its `__init__` with `<string>` too,
    but the frame calling `exec` is `dataclasses.py`.

    Args:
        frame: The frame of the caller reaching a patched builtin.

    Returns:
        Whether the call comes from library or runtime code.
    """
    filename = frame.f_code.co_filename
    if filename.startswith(TAG_PREFIX):
        return False
    if filename.startswith("<frozen "):
        return True
    resolved = str(Path(filename).resolve())
    if _STDLIB_ROOTS and resolved.startswith(_STDLIB_ROOTS):
        return True
    return any(segment in Path(resolved).parts for segment in _VENDOR_SEGMENTS)


def _source_ref(frame: types.FrameType, profile: str) -> str:
    """Return the `<eval:...>` filename `compile` stamps for this call."""
    del frame
    return f"{TAG_PREFIX}{profile or 'default'}>"


def _call_site(frame: types.FrameType) -> str:
    """Return `file.py:line` for the application frame making the call."""
    return f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}"


def _guarded_source(source: Any, qualname: str) -> str:
    """Return the source string, or refuse a code object the guard did not make.

    A code object cannot be validated after the fact. Guarded `compile` stamps
    its output with the `<eval:` filename, and only that stamp is accepted
    here.

    Args:
        source: What the caller passed as the first argument.
        qualname: The patched builtin, for the refusal message.

    Returns:
        The source text, or `""` for a code object the guard itself produced.

    Raises:
        RuleApiPermissionError: A code object of unknown provenance.
    """
    if isinstance(source, str):
        return source
    if isinstance(source, (bytes, bytearray)):
        return source.decode("utf-8", errors="replace")
    if getattr(source, "co_filename", "").startswith(TAG_PREFIX):
        return ""
    raise RuleApiPermissionError(f"{qualname} on a code object the guard did not produce", "python-api=ALLOW")


def _learn_from(source: Any, qualname: str, mode: str, rules: EvalRules | None) -> None:
    """Record what an unguarded call would have needed, without refusing it.

    Args:
        source: What the caller passed to the patched builtin.
        qualname: The builtin reached, recorded so `generate_rules` emits the
            `dynamic-code` line beside the `eval-*` ones.
        mode: `"eval"` or `"exec"`.
        rules: The declared profile, or None when the configuration has no
            `eval-*` key at all.
    """
    add_learning_rule(LearnApiRule(qualname))
    if not isinstance(source, (str, bytes, bytearray)):
        # A code object carries no syntax to validate.
        return
    text = source if isinstance(source, str) else source.decode("utf-8", errors="replace")
    try:
        tree = ast.parse(text, mode=mode if mode in ("eval", "exec") else "exec")
    except SyntaxError:
        # The application's own problem, and it is about to raise it itself.
        return
    for key, name in learn_targets(validate(tree, rules or DEFAULT_RULES)):
        add_learning_rule(LearnEvalRule(key, name))


def _wrap_eval_like(func: Callable[..., Any], *, qualname: str, mode: str) -> Callable[..., Any]:
    """Wrap `builtins.eval` or `builtins.exec`.

    Precedence, written once, here, and nowhere else:
    unarmed, then ambient, then `python-api=ALLOW:dynamic-code`, then a
    declared profile, then refusal.

    Args:
        func: The original builtin.
        qualname: Its dotted name, for refusals and `is_allowed`.
        mode: `"eval"` or `"exec"`.

    Returns:
        The replacement callable.
    """
    if getattr(func, "__pysandbox_eval__", False):
        return func

    @functools.wraps(func)
    def wrapper(
        source: Any,
        globals_: dict[str, Any] | None = None,
        locals_: Any = None,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        frame = sys._getframe(1)
        # eval() with no globals resolves in the frame of *its* caller, which
        # once wrapped is this wrapper. Reconstruct before delegating.
        raw_globals = globals_ if globals_ is not None else frame.f_globals
        raw_locals = locals_ if locals_ is not None else (frame.f_locals if globals_ is None else raw_globals)
        if not guard_api.is_armed() or is_ambient(frame) or guard_api.is_allowed(qualname):
            return func(source, raw_globals, raw_locals, *args, **kwargs)
        rules = _profiles.get("")
        if is_learning_mode():
            # Learning observes, it never blocks: refusing here would stop the
            # application on its first eval and there would be nothing left to
            # learn from. The source is validated against the profile in force
            # -- deny-all when none is declared, which is what makes every
            # construct show up as a rule to propose -- and then runs through
            # the raw builtin so the run reaches its end.
            _learn_from(source, qualname, mode, rules)
            return func(source, raw_globals, raw_locals, *args, **kwargs)
        if rules is None or not rules.declared:
            raise RuleApiPermissionError(qualname, "dynamic-code")
        if rules.namespace == "caller":
            # Honouring the caller's namespace means honouring CPython's
            # injection, which means not rewriting: injected __sb_getattr__
            # calls into a namespace without the helpers would raise
            # NameError on the first attribute read. The debugging escape
            # hatch is therefore a straight passthrough.
            return func(source, raw_globals, raw_locals, *args, **kwargs)
        text = _guarded_source(source, qualname)
        if not text:
            return func(source, raw_globals, raw_locals, *args, **kwargs)
        if globals_ is not None and rules.namespace == "adaptive":
            warn_about_context(globals_, _call_site(frame))
            add_learning_rule(LearnEvalContext(_call_site(frame)))
        namespace = build_namespace(rules, caller_globals=globals_, names=None, from_wrapper=False)
        return run_guarded(text, rules, mode=mode, namespace=namespace, source_ref=_source_ref(frame, ""))

    wrapper.__pysandbox_eval__ = True  # type: ignore[attr-defined]
    return wrapper


def _wrap_compile(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap `builtins.compile`, stamping guarded output with the `<eval:` tag.

    Args:
        func: The original builtin.

    Returns:
        The replacement callable.
    """
    if getattr(func, "__pysandbox_eval__", False):
        return func

    @functools.wraps(func)
    def wrapper(source: Any, filename: Any = "<string>", mode: Any = "exec", /, *args: Any, **kwargs: Any) -> Any:
        frame = sys._getframe(1)
        if not guard_api.is_armed() or is_ambient(frame) or guard_api.is_allowed("builtins.compile"):
            return func(source, filename, mode, *args, **kwargs)
        rules = _profiles.get("")
        if rules is None or not rules.declared:
            raise RuleApiPermissionError("builtins.compile", "dynamic-code")
        if rules.namespace == "caller":
            return func(source, filename, mode, *args, **kwargs)
        text = _guarded_source(source, "builtins.compile")
        ref = _source_ref(frame, "")
        tree = ast.parse(text, filename=ref, mode=mode if mode in ("eval", "exec") else "exec")
        raise_if_rejected(ref, text, validate(tree, rules))
        return func(cast("ast.Module | ast.Expression", inject(tree)), ref, mode, *args, **kwargs)

    wrapper.__pysandbox_eval__ = True  # type: ignore[attr-defined]
    return wrapper


def patch_rules(learn: bool) -> dict[str, Callable[..., Any]]:
    """Return the patch table for the three dynamic-code builtins.

    Args:
        learn: Accepted for symmetry with the other guards; the decision is a
            rule lookup made at call time, not at patch time.

    Returns:
        The patch table, keyed by dotted name.
    """
    del learn
    return {
        "builtins.eval": _f(_wrap_eval_like, qualname="builtins.eval", mode="eval"),
        "builtins.exec": _f(_wrap_eval_like, qualname="builtins.exec", mode="exec"),
        "builtins.compile": _f(_wrap_compile),
    }


if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:

    def _deactivate_guard_eval() -> None:
        """Reset the guard between tests."""
        global _profiles, _leaked
        _profiles = ImmutableDict({})
        _leaked = 0
        _reset_context_warnings()
