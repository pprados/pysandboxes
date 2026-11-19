# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Guard for code that arrives as a string at runtime.

`builtins.eval`, `builtins.exec` and `builtins.compile` are patched here, and
`string.Formatter.get_field`, whose attribute reads no rewrite can reach, and
`marshal.loads`/`marshal.load`, which hand back a runnable code object with no
source for this guard to parse. A guarded call parses the source, validates it
against the sub-language the `eval-*` rules describe, rewrites it so the
remaining risks are enforced by `eval_runtime`, and runs it in a dedicated
thread under a budget and a timeout the caller can recover from; `marshal`
has no source to run this way, so it is only ever allowed or refused whole,
the same binary choice `guard_api` gives its own registry.

Two choices a later reader should not "restore":

- `SENSITIVE_API["dynamic-code"]` holds five names: `eval`, `exec`, `compile`,
  `marshal.loads` and `marshal.load`. `builtins.__import__` is left out because
  `guard_import` owns it with its own rules; `code.compile_command` and
  `code.InteractiveInterpreter.runsource` are left out because they reach the three
  builtins anyway -- genuinely, not just nominally: `is_ambient`'s `_GATEWAYS` walk
  past their own stdlib frame to the real caller, instead of stopping at the first
  stdlib frame and calling it ambient -- so patching them too would count one call
  twice.
- CPython's automatic injection of the 159 builtins into a namespace that lacks
  `__builtins__` is never honoured under `eval-namespace=adaptive` or `closed`.
  `eval-namespace=caller` is the debugging escape hatch: it does honour the
  injection, and a warning is logged when the rule is loaded.

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
- A field resolved by a host callable during the evaluation. `str.format`
  templates are validated by `__sb_getattr__`, `string.Formatter` fields by
  the patched `get_field`; a native or third-party formatter that walks
  attributes on its own is not seen. Such a callable reaches the evaluated
  code only if the application passes it in.
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
import logging
import os
import sys
import sysconfig
import threading
import types
import weakref
from pathlib import Path
from typing import Any, Callable, NoReturn, cast

from . import guard_api, guard_files
from .e import EvalInterrupted, RuleApiPermissionError
from .eval_rules import CAPABILITY_BUILTINS, DEFAULT_RULES, EvalProfiles, EvalRules, LearnEvalContext, LearnEvalRule
from .eval_runtime import (
    GUARDED_BUILTINS,
    HELPERS,
    EvalState,
    check_format_field,
    in_evaluation,
    pop_state,
    push_state,
)
from .eval_transform import Violation, inject, learn_targets, raise_if_rejected, validate
from .guard_api import LearnApiRule
from .guard_wraps import guard_wraps
from .immutable_dict import ImmutableDict
from .learning import add_learning_rule, is_learning_mode
from .lifecycle import is_armed
from .main_logger import ErrorMsg, format_ruleref
from .sb_types import ConfigLines
from .tools import patch_factory as _f

logger = logging.getLogger(__name__)

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

        post: __return__ in ('strong', 'weak', '')
        post: not isinstance(value, types.ModuleType) or __return__ == 'strong'
        post: not isinstance(value, _SCALARS) or callable(value) or __return__ == ''
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
            allowed[name] = GUARDED_BUILTINS.get(name) or getattr(builtins, name)
    return allowed


def build_namespace(
    rules: EvalRules,
    *,
    caller_globals: dict[str, Any] | None,
    names: dict[str, Any] | None,
    from_wrapper: bool,
) -> dict[str, Any]:
    """Return the globals the evaluated code will see.

    The namespace depends on who calls and on `eval-namespace`: `guarded_eval`
    always gets a fresh closed namespace plus `names`; the patched builtin
    reuses the caller's own globals under `adaptive` and builds a fresh one
    under `closed`; `caller` never reaches here. The dividing line for the
    patched builtin is `caller_globals is None`, not "arguments were passed":
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
"""Filename prefix guarded `compile` stamps on its output, for tracebacks."""

_produced: "weakref.WeakKeyDictionary[types.CodeType, tuple[str, str]]" = weakref.WeakKeyDictionary()
"""Each code object guarded `compile` returned, with its source and the mode to parse it in. A filename proves
nothing: any code object can be given the `<eval:` one with `code.replace(co_filename=...)`."""

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


_swap_lock = threading.Lock()


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
    # Two evaluations swapping at once would let the second one save the raw primitives as the patched ones,
    # and restore them for good.
    with _swap_lock:
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
_leaked: list[threading.Event] = []
_leak_lock = threading.Lock()
_inline = False


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
    with _leak_lock:
        # A worker whose C call finally returned no longer burns anything.
        _leaked[:] = [done for done in _leaked if not done.is_set()]
        return len(_leaked)


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


def _raise_parse_overflow(source_ref: str, source: str) -> NoReturn:
    """Reject source that overflows the parser before there is a tree to measure.

    `ast.parse` recurses with the grammar, so deeply nested input can exhaust
    the interpreter's C stack before returning a tree for `validate`'s
    `_depth` check to measure -- `RecursionError` on CPython's
    recursive-descent builds (3.11), `MemoryError` ("Parser stack
    overflowed") on the PEG parser (3.14 here). Same refusal `validate`
    already gives a tree too deep to walk, one step earlier.

    Raises:
        EvalSyntaxRejected: Always.
    """
    raise_if_rejected(
        source_ref,
        source,
        [Violation(1, 0, "the source defeats the parser before it can be measured", "eval-max-depth=parse")],
    )
    raise AssertionError("unreachable: raise_if_rejected always raises for a non-empty violation list")


def run_workers_inline() -> None:
    """Run every evaluation on the calling thread, from now on.

    The worker thread only isolates a blocking C call from the caller's timeout. A measured run (coverage) has
    no use for that, and a trace hook cannot follow a thread the guards forbid it to hook.
    """
    global _inline
    _inline = True


def _run_in_worker_thread(
    code: Any,
    mode: str,
    namespace: dict[str, Any],
    state: EvalState,
    box: dict[str, Any],
    rules: EvalRules,
    source_ref: str,
) -> None:
    done = threading.Event()

    def run_worker() -> None:
        try:
            _worker(code, mode, namespace, state, box)
        finally:
            done.set()

    worker = threading.Thread(
        target=run_worker,
        name=f"guard_eval{source_ref}",
        daemon=True,
    )
    _start_unguarded(worker)
    try:
        worker.join(rules.timeout + _JOIN_GRACE)
    except BaseException:
        _interrupt(state, rules.timeout)
        if not done.is_set():
            with _leak_lock:
                _leaked.append(done)
        raise
    if not done.is_set():
        # A blocking C call never returns to a tick. The caller gets its
        # exception; the thread keeps burning CPU, cumulatively across calls.
        # The real guarantee is the OS layer, where a timeout is a process
        # kill. Documented as a limit, not presented as covered.
        with _leak_lock:
            _leaked.append(done)
        logger.warning("guard_eval: %s did not stop; %d leaked thread(s)", source_ref, leaked_threads())
        raise EvalInterrupted(f"eval-timeout={rules.timeout}s exhausted, and the worker did not stop")


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
    learn = is_learning_mode()
    leaks = leaked_threads()
    if leaks and leaks >= rules.max_leaked_threads:
        raise EvalInterrupted(
            f"eval-max-leaked-threads={rules.max_leaked_threads} reached: "
            "earlier evaluations blocked in a C call and are still running"
        )
    try:
        tree = ast.parse(source, filename=source_ref, mode=mode)
    except (RecursionError, MemoryError):
        _raise_parse_overflow(source_ref, source)
    supplied = {
        id(value): value
        for key, value in namespace.items()
        if key not in HELPERS and key != "__builtins__" and hasattr(type(value), "__setitem__")
    }
    state = EvalState(rules, learn=learn, supplied=supplied)
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
    watchdog = threading.Timer(rules.timeout, _interrupt, args=(state, rules.timeout))
    try:
        _start_unguarded(watchdog)
        if _inline:
            _worker(code, mode, namespace, state, box)
        else:
            _run_in_worker_thread(code, mode, namespace, state, box, rules, source_ref)
    finally:
        watchdog.cancel()
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

# Whole stdlib files entirely dedicated to running a line, a statement, or a script the caller
# supplies -- a debugger, a profiler, a tracer, the two REPL classes, timeit, runpy, codeop.
# `is_ambient` does not conclude on a frame in one of these: the *caller's* code, not this
# forwarding frame's, produced the source being run, so the walk continues to `frame.f_back`
# instead. A whole file, not a `(file, qualname)` pair as `_GATEWAYS` below uses for a
# mixed-purpose file: these modules' public entry points (`code.InteractiveInterpreter.runsource`,
# `timeit.timeit`, `runpy.run_module`) reach the actual exec/eval/compile call through several
# private helpers apiece (`codeop.CommandCompiler.__call__` -> `_maybe_compile` ->
# `codeop.Compile.__call__` -> `compile()`, measured on 3.11-3.14), and naming every one of
# them, here and again after the next refactor, is the wrong level of detail for what is, in
# every one of these files, a single-purpose module. Keyed the same way `_GATEWAYS` is, by
# `_module_key()`.
_GATEWAY_FILES: frozenset[str] = frozenset(
    {
        "code.py",
        "codeop.py",
        "bdb.py",
        "pdb.py",
        "doctest.py",
        "profile.py",
        "cProfile.py",
        "trace.py",
        "timeit.py",
        "runpy.py",
        "rlcompleter.py",
    }
)

# Individual functions of an otherwise ordinary stdlib file whose one job is to compile,
# evaluate, or run a string, file, or byte stream the caller hands it. Keyed by
# `(module_key, qualified name)`, `module_key` from `_module_key()`: the dotted module name with
# its separators turned into `/` and `.py` appended, e.g. `importlib/_bootstrap.py`,
# `importlib/abc.py`, `runpy.py` -- the same key whether CPython freezes that module at build
# time (`co_filename` then reports `<frozen pkg.mod>`, never a real path) or reads it from its
# `.py` file, which varies by module *and by CPython version*: `runpy` is frozen by default from
# 3.11, `_bootstrap`/`_bootstrap_external` always were. A table keyed on `<frozen ...>` only for
# the ones observed frozen on one interpreter would silently stop matching on a build, or a
# future version, that freezes a different set.
#
# Found by an AST scan of the stdlib of every supported Python (3.11 through 3.14) for an
# exec/eval/compile call whose argument is not a literal constant
# (`tests/unit_tests/guard/test_guard_eval_ambient_gateways.py` re-runs the scan on the current
# interpreter and fails when it finds one covered by neither this table, `_GATEWAY_FILES` above,
# nor `_GATEWAY_EXCLUSIONS` below), plus three the scan cannot see because they pass the builtin
# by reference through `importlib._bootstrap._call_with_frames_removed` instead of naming it:
# that function itself, and the two `_bootstrap_external.SourceLoader` methods it protects.
# Without those three, a direct `SourceFileLoader(name, path).get_code(name)` -- unlike a real
# import -- would stop at the first of them and stay ambient, because every frame up to the real
# caller is itself frozen.
_GATEWAYS: frozenset[tuple[str, str]] = frozenset(
    {
        # The import machinery's own compile/exec/marshal.loads, reached directly when a loader
        # or a bytecode blob is driven by hand instead of through `find_spec`.
        # `guard_import._vetted_loaders` closes the same route for `exec_module` itself; these
        # close it for `source_to_code`/`get_code`/`_compile_bytecode` called on their own. A
        # legitimate import walks back up through the same frozen frames to `_find_and_load`,
        # where the walk stops (frozen, not a gateway) and the import stays ambient.
        ("importlib/_bootstrap.py", "_call_with_frames_removed"),
        ("importlib/_bootstrap_external.py", "SourceLoader.source_to_code"),
        ("importlib/_bootstrap_external.py", "SourceLoader.get_code"),
        ("importlib/_bootstrap_external.py", "_compile_bytecode"),
        ("importlib/abc.py", "InspectLoader.source_to_code"),
        ("zipimport.py", "_compile_source"),
        ("zipimport.py", "_unmarshal_code"),
        ("zipimport.py", "zipimporter.load_module"),
        ("pkgutil.py", "read_code"),
        ("dis.py", "_try_compile"),
        ("dis.py", "main"),
        ("py_compile.py", "main"),
        ("optparse.py", "Values.read_file"),
        ("logging/config.py", "_create_formatters"),
        ("logging/config.py", "_install_handlers"),
        ("site.py", "addpackage"),
    }
)

# Candidates the scan also finds, deliberately left out of `_GATEWAYS`: the argument is not
# meaningfully caller-supplied, so `is_ambient` keeps judging the *library's* frame, as before.
_GATEWAY_EXCLUSIONS: dict[tuple[str, str], str] = {
    ("dataclasses.py", "_create_fn"): "compiles a template the library built from field "
    "names it already validated as identifiers, not the caller's source",
    ("dataclasses.py", "_FuncBuilder.add_fns_to_class"): "same as _create_fn, batched",
    ("collections/__init__.py", "namedtuple"): "field_names are validated as identifiers "
    "before the generated lambda is eval'd",
    ("typing.py", "ForwardRef.__init__"): "compiles a type-annotation string the application "
    "wrote in its own source; required for pydantic and dataclasses",
    ("typing.py", "ForwardRef._evaluate"): "evaluates the same forward-ref string",
    ("annotationlib.py", "ForwardRef.evaluate"): "3.14 equivalent of typing.ForwardRef._evaluate",
    ("annotationlib.py", "ForwardRef.__forward_code__"): "compiles the same forward-ref string",
    ("annotationlib.py", "get_annotations"): "evaluates a type-annotation string, like inspect.get_annotations",
    ("inspect.py", "get_annotations"): "evaluates a type-annotation string the application wrote",
    ("inspect.py", "_signature_fromstr.wrap_value"): "evaluates a repr() the library itself "
    "produced while parsing a C function's text signature",
    ("unittest/mock.py", "_set_signature"): "execs a wrapper template built from the mocked callable's own signature",
    ("unittest/mock.py", "_set_async_signature"): "same as _set_signature, for an async callable",
    ("multiprocessing/managers.py", "MakeProxyType"): "execs a class template built from method "
    "names given at class-definition time, not at call time",
    ("multiprocessing/sharedctypes.py", "make_property"): "execs a property template built from a validated field name",
    ("ast.py", "parse"): "compiles with PyCF_ONLY_AST: produces a tree, never runs anything",
    ("importlib/_bootstrap.py", "FrozenImporter.exec_module"): "the name only selects a module "
    "already frozen into the interpreter at build time; nothing the caller supplies is run",
    ("pydoc.py", "Helper.help"): "the eval() is only ever reached for 'True', 'False' or "
    "'None', gated by an equality check two lines above it",
    ("modulefinder.py", "ModuleFinder.load_module"): "static dependency-analysis tooling, not "
    "reachable from sandboxed code at runtime",
    ("pkgutil.py", "ImpLoader.get_code"): "the deprecated imp-era compatibility loader, removed "
    "from the stdlib in 3.12",
    ("gettext.py", "c2py"): "the plural-form expression is parsed by a small grammar first, "
    "restricted to C-style arithmetic/comparison/ternary on one name, before the validated "
    "result is embedded in the exec'd template -- the same shape of validation as namedtuple's",
}

# Whole files excluded the same way, one reason covering every candidate the scan finds there.
_GATEWAY_EXCLUDED_FILE_PREFIXES: dict[str, str] = {
    "idlelib/": "IDLE is a GUI developer tool, never reachable from a sandboxed process",
    "turtle.py": "turtle graphics; GUI-only, never reachable from a sandboxed process",
    "tkinter/": "Tk; GUI-only, never reachable from a sandboxed process",
    "distutils/": "removed from the stdlib in 3.12, deprecated before that",
    "_pyrepl/": "the interactive interpreter's own REPL, a developer tool",
    "asyncio/__main__.py": "python -m asyncio's interactive REPL, a developer tool",
}

# pysandboxes' own dispatch of the sandboxed program's `-m` module: the Python-level stand-in for
# the frame-less C-level call a plain `python -m pkg.mod` makes. A real `-m` launch has no Python
# frame above the frozen import machinery, so the gateway walk below runs out of frames (or meets
# another frozen one) and concludes ambient; `_python_module` inserts non-stdlib frames there
# instead, which the walk would otherwise read as the application's own call site, denying the
# `_compile_bytecode`/`marshal.loads` read of the entry module's own `.pyc` cache. Scoped to the
# one-time frames that load the entry point -- the direct callers of `runpy.run_module` and of
# `main_sandbox.py`'s own dispatch -- never to a frame of the entry point's code once it runs:
# that code's own `eval`/`exec`/`compile`/`marshal.loads` calls still have the entry module's own
# frame as their immediate caller, which matches none of these and stays judged. Keyed like
# `_GATEWAYS`, resolved against the pysandboxes package root instead of the stdlib root.
_FRAMEWORK_ROOT = str(Path(__file__).resolve().parent)
_FRAMEWORK_GATEWAYS: frozenset[tuple[str, str]] = frozenset(
    {
        ("remote/python_in_sb.py", "_python_module"),
        ("remote/python_in_sb.py", "python_in_sb"),
        ("remote/main_sandbox.py", "main"),
        ("remote/main_sandbox.py", "run_guest"),
        ("remote/main_sandbox.py", "<module>"),
    }
)


def _framework_key(filename: str) -> str | None:
    """Return this frame's `_FRAMEWORK_GATEWAYS` key, or `None` when it is not under the package root."""
    resolved = guard_files._safe_realpath(filename)
    if resolved.startswith(_FRAMEWORK_ROOT):
        return Path(resolved[len(_FRAMEWORK_ROOT) :].lstrip("/\\")).as_posix()
    return None


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

    A stdlib or frozen frame is not the end of it, though: some stdlib functions exist
    specifically to compile or run a string, a file, or a code object *the caller* supplies --
    `importlib.abc.InspectLoader.source_to_code`, `code.InteractiveInterpreter.runsource`,
    `timeit.timeit`, a debugger's `exec` of a breakpoint command, and so on. Calling one of these
    directly is indistinguishable, one frame at a time, from the library legitimately calling
    itself: both have a stdlib frame as the immediate caller. The walk resolves it by not
    stopping there: for a frame in `_GATEWAY_FILES` or `_GATEWAYS`, it keeps climbing past every
    such frame until it reaches either the frozen import machinery (a real import, stay ambient)
    or a frame that is not stdlib/frozen/vendor at all (the application's own code, not ambient)
    or another stdlib frame that is not itself a gateway (the library calling itself for an
    unrelated reason, stay ambient, the original rule).

    Args:
        frame: The frame of the caller reaching a patched builtin.

    Returns:
        Whether the call comes from library or runtime code.
    """
    current: types.FrameType | None = frame
    while current is not None:
        code = current.f_code
        filename = code.co_filename
        if filename.startswith(TAG_PREFIX):
            return False
        framework_key = _framework_key(filename)
        if framework_key is not None and (framework_key, code.co_qualname) in _FRAMEWORK_GATEWAYS:
            current = current.f_back
            continue
        module_key, resolved = _module_key(filename)
        if module_key is not None:
            if module_key in _GATEWAY_FILES or (module_key, code.co_qualname) in _GATEWAYS:
                current = current.f_back
                continue
            return True
        return any(segment in Path(resolved).parts for segment in _VENDOR_SEGMENTS)
    # Ran out of frames without finding a non-gateway one: nothing but forwarding functions all
    # the way to the bottom of the stack, which only happens from a C-level call with no Python
    # frame beneath it (interpreter startup, an embedder). Not sandboxed code either way.
    return True


def _module_key(filename: str) -> tuple[str | None, str]:
    """Return `(module_key, resolved)`: `_GATEWAYS`/`_GATEWAY_FILES`' lookup key for `filename`,
    or `None` as the first element when it is neither frozen nor under a stdlib root.

    A frozen module's `co_filename` (`<frozen pkg.mod>`) is turned into the same
    `pkg/mod.py`-style key a `.py`-file frame resolves to, relative to the stdlib root: which
    modules CPython freezes at build time varies by module and by version (`runpy` only from
    3.11; `importlib._bootstrap`/`_bootstrap_external` always), and the table must match either
    way. `resolved` is the real, canonicalized path for a non-frozen frame (for the vendor check
    the caller falls back to when `module_key` is `None`), or `filename` unchanged when frozen.
    """
    if filename.startswith("<frozen ") and filename.endswith(">"):
        dotted = filename[len("<frozen ") : -1]
        return dotted.replace(".", "/") + ".py", filename
    # Path.resolve() calls os.path.realpath(), whose lstat/readlink calls are
    # patched by guard_files. Use its guarded canonicalizer to avoid re-entering
    # those wrappers while deciding whether this is framework-generated code.
    resolved = guard_files._safe_realpath(filename)
    for root in _STDLIB_ROOTS:
        if resolved.startswith(root):
            return Path(resolved[len(root) :].lstrip("/\\")).as_posix(), resolved
    return None, resolved


def _source_ref(frame: types.FrameType, profile: str) -> str:
    """Return the `<eval:...>` filename `compile` stamps for this call."""
    del frame
    return f"{TAG_PREFIX}{profile or 'default'}>"


def _call_site(frame: types.FrameType) -> str:
    """Return `file.py:line` for the application frame making the call."""
    return f"{Path(frame.f_code.co_filename).name}:{frame.f_lineno}"


def _guarded_source(source: Any, qualname: str, mode: str) -> tuple[str, str]:
    """Return the source text to validate, or refuse a code object the guard did not make.

    A code object cannot be validated after the fact. One guarded `compile`
    returned is run again from its source, under the same budgets and
    watchdog as a string. A tree, which `compile(..., ast.PyCF_ONLY_AST)`
    returns, is validated as the source it unparses to.

    Args:
        source: What the caller passed as the first argument.
        qualname: The patched builtin, for the refusal message.
        mode: The mode the builtin was called in.

    Returns:
        The source text, and the mode to parse it in.

    Raises:
        RuleApiPermissionError: A code object of unknown provenance.
    """
    if isinstance(source, str):
        return source, mode
    if isinstance(source, (bytes, bytearray)):
        return source.decode("utf-8", errors="replace"), mode
    if isinstance(source, ast.AST):
        return ast.unparse(source), mode
    if isinstance(source, types.CodeType) and source in _produced:
        return _produced[source]
    raise RuleApiPermissionError(f"{qualname} on a code object the guard did not produce", "python-api=ALLOW")


def _learn_from(source: Any, qualname: str, mode: str, rules: EvalRules | None) -> None:
    """Record what the guarded path would need, without refusing the call.

    A source string is served by the `eval-*` rules: proposing
    `python-api=ALLOW` beside them would send it to the raw builtin, past the
    sub-language. Only a code object the guard did not produce needs that
    right, as the guarded path refuses it.

    Args:
        source: What the caller passed to the patched builtin.
        qualname: The builtin reached, recorded so `generate_rules` emits the
            `dynamic-code` line when a code object needs it.
        mode: `"eval"` or `"exec"`.
        rules: The declared profile, or None when the configuration has no
            `eval-*` key at all.
    """
    if not isinstance(source, (str, bytes, bytearray, ast.AST)):
        # A code object carries no syntax to validate.
        if not (isinstance(source, types.CodeType) and source in _produced):
            add_learning_rule(LearnApiRule(qualname))
        return
    text, _ = _guarded_source(source, qualname, mode)
    try:
        tree = ast.parse(text, mode=mode if mode in ("eval", "exec") else "exec")
    except (SyntaxError, RecursionError, MemoryError):
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

    @guard_wraps(func)
    def wrapper(source: Any, /, *args: Any, **kwargs: Any) -> Any:
        # eval/exec take globals and locals positionally or by keyword. The
        # wrapper must accept both without narrowing them, or a plain
        # eval(code, globals=..., locals=...) raises TypeError before any rule
        # is evaluated. Whatever remains is exec()'s keyword-only closure.
        globals_: dict[str, Any] | None = args[0] if len(args) >= 1 else kwargs.pop("globals", None)
        locals_: Any = args[1] if len(args) >= 2 else kwargs.pop("locals", None)
        extra = args[2:]
        frame = sys._getframe(1)
        # eval() with no globals resolves in the frame of *its* caller, which
        # once wrapped is this wrapper. Reconstruct before delegating.
        raw_globals = globals_ if globals_ is not None else frame.f_globals
        raw_locals = locals_ if locals_ is not None else (frame.f_locals if globals_ is None else raw_globals)
        if not isinstance(raw_locals, dict):
            # PEP 667 (3.13+): a function's f_locals writes through to its variables, where the native builtin
            # works on a snapshot.
            raw_locals = dict(raw_locals)
        if not is_armed() or is_ambient(frame) or guard_api.is_allowed(qualname):
            return func(source, raw_globals, raw_locals, *extra, **kwargs)
        rules = _profiles.get("")
        if is_learning_mode():
            # Learning observes, it never blocks: refusing here would stop the
            # application on its first eval and there would be nothing left to
            # learn from. The source is validated against the profile in force
            # -- deny-all when none is declared, which is what makes every
            # construct show up as a rule to propose -- and then runs through
            # the raw builtin so the run reaches its end.
            _learn_from(source, qualname, mode, rules)
            return func(source, raw_globals, raw_locals, *extra, **kwargs)
        if rules is None or not rules.declared:
            raise RuleApiPermissionError(qualname, "dynamic-code")
        if rules.namespace == "caller":
            # Honouring the caller's namespace means honouring CPython's
            # injection, which means not rewriting: injected __sb_getattr__
            # calls into a namespace without the helpers would raise
            # NameError on the first attribute read. The debugging escape
            # hatch is therefore a straight passthrough.
            return func(source, raw_globals, raw_locals, *extra, **kwargs)
        text, text_mode = _guarded_source(source, qualname, mode)
        if globals_ is not None and rules.namespace == "adaptive":
            warn_about_context(globals_, _call_site(frame))
            add_learning_rule(LearnEvalContext(_call_site(frame)))
        namespace = build_namespace(rules, caller_globals=globals_, names=None, from_wrapper=False)
        result = run_guarded(text, rules, mode=text_mode, namespace=namespace, source_ref=_source_ref(frame, ""))
        return None if mode == "exec" else result

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

    @guard_wraps(func)
    def wrapper(source: Any, filename: Any = "<string>", mode: Any = "exec", *args: Any, **kwargs: Any) -> Any:
        frame = sys._getframe(1)
        if not is_armed() or is_ambient(frame) or guard_api.is_allowed("builtins.compile"):
            return func(source, filename, mode, *args, **kwargs)
        rules = _profiles.get("")
        if rules is None or not rules.declared:
            raise RuleApiPermissionError("builtins.compile", "dynamic-code")
        if rules.namespace == "caller":
            return func(source, filename, mode, *args, **kwargs)
        text, text_mode = _guarded_source(source, "builtins.compile", mode)
        text_mode = text_mode if text_mode in ("eval", "exec") else "exec"
        ref = _source_ref(frame, "")
        try:
            tree = ast.parse(text, filename=ref, mode=text_mode)
        except (RecursionError, MemoryError):
            _raise_parse_overflow(ref, text)
        raise_if_rejected(ref, text, validate(tree, rules))
        flags = args[0] if args else kwargs.get("flags", 0)
        if flags & ast.PyCF_ONLY_AST:
            # The tree as written: compiling it later comes back here and is validated again.
            return tree
        code = func(cast("ast.Module | ast.Expression", inject(tree)), ref, mode, *args, **kwargs)
        _produced[code] = (text, text_mode)
        return code

    wrapper.__pysandbox_eval__ = True  # type: ignore[attr-defined]
    return wrapper


def _wrap_marshal(func: Callable[..., Any], *, qualname: str) -> Callable[..., Any]:
    """Wrap `marshal.loads`/`marshal.load`.

    Unlike `eval`/`exec`/`compile`, there is no source text to parse, validate, or rewrite: the
    call either hands back a code object the caller can run without ever touching a guarded
    builtin again (`types.FunctionType(code, globals)()`, `f.__code__ = code`), or it does not
    run at all. The decision is therefore the plain allow/deny `guard_api` gives its own
    registry, not an `eval-*` profile; `is_ambient` is reused as-is, since a `.pyc`-cache read
    walks the same `_GATEWAYS` frames a real import does, through `_compile_bytecode`,
    `zipimport._unmarshal_code` and `pkgutil.read_code`.

    Args:
        func: The original `marshal.loads` or `marshal.load`.
        qualname: Its dotted name, for the registry, refusals, and learning.

    Returns:
        The replacement callable.
    """
    if getattr(func, "__pysandbox_eval__", False):
        return func

    @guard_wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        frame = sys._getframe(1)
        if not is_armed() or is_ambient(frame) or guard_api.is_allowed(qualname):
            return func(*args, **kwargs)
        if is_learning_mode():
            add_learning_rule(LearnApiRule(qualname))
            return func(*args, **kwargs)
        raise RuleApiPermissionError(qualname, "dynamic-code")

    wrapper.__pysandbox_eval__ = True  # type: ignore[attr-defined]
    return wrapper


def _wrap_formatter_get_field(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap `string.Formatter.get_field`, the one attribute read of `string.Formatter`.

    `Formatter.format`, `vformat` and `_vformat` resolve `{0.__class__}` with a
    plain `getattr` in `get_field`, which the bounded namespace never sees.
    Every field reaches this method, whatever parse produced it, so checking
    here covers a subclass whose `parse` lies to a validation done beforehand.
    Outside a guarded evaluation the method is untouched.

    Args:
        func: The original method.

    Returns:
        The replacement method.
    """

    @guard_wraps(func)
    def wrapper(self: Any, field_name: Any, *args: Any, **kwargs: Any) -> Any:
        if in_evaluation():
            check_format_field(field_name)
        return func(self, field_name, *args, **kwargs)

    return wrapper


def check_api_grants(api_rules: guard_api.ApiRules, eval_lines: ConfigLines, errors: list[ErrorMsg]) -> None:
    """Refuse the `eval-*` rules a `python-api` grant leaves unused.

    A granted eval, exec or compile runs the code through the raw builtin before any `eval-*` rule is read: the
    rules would look in force and guard nothing.
    """
    if not eval_lines:
        return
    decisions = guard_api.resolve(api_rules)
    granted = [qualname for qualname in guard_api.SENSITIVE_API["dynamic-code"] if decisions[qualname]]
    if not granted:
        return
    for rule in eval_lines:
        errors.append(
            (
                f"{format_ruleref(rule)}: {rule.rule!r} is never applied, python-api grants "
                f"{', '.join(granted)} unguarded: comment it out, or remove the grant.",
                rule.path,
                rule.ln,
            )
        )


def patch_rules(learn: bool) -> dict[str, Callable[..., Any]]:
    """Return the patch table for the dynamic-code builtins and `marshal`.

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
        "string.Formatter.get_field": _f(_wrap_formatter_get_field),
        "marshal.loads": _f(_wrap_marshal, qualname="marshal.loads"),
        "marshal.load": _f(_wrap_marshal, qualname="marshal.load"),
    }


if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:

    def _deactivate_guard_eval() -> None:
        """Reset the guard between tests."""
        global _profiles
        _profiles = ImmutableDict({})
        _leaked.clear()
        _reset_context_warnings()
