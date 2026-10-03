# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Guard denying calls to sensitive functions.

Import rights and call rights are distinct: a module may be importable
while some of its functions must stay unreachable. This guard denies
calls to a finite registry of sensitive functions, independently of
``python-import=``, and records attempted calls in learning mode.
"""

import logging
import os
import sys
from typing import Any, Callable, NamedTuple

from .e import RuleApiPermissionError
from .guard_wraps import guard_wraps
from .immutable_dict import ImmutableDict
from .learning import add_learning_rule, is_learning_mode
from .lifecycle import is_armed as _lc_is_armed
from .main_logger import ErrorMsg, format_ruleref
from .sb_types import ConfigLine, ConfigLines
from .tools import patch_factory as _f

logger = logging.getLogger(__name__)

SENSITIVE_API: dict[str, tuple[str, ...]] = {
    "process-exec": (
        "os.system",
        "posix.system",
        "os.popen",
        "os.execv",
        "posix.execv",
        "os.execve",
        "posix.execve",
        "os.execl",
        "os.execle",
        "os.execlp",
        "os.execlpe",
        "os.execvp",
        "os.execvpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.posix_spawn",
        "posix.posix_spawn",
        "os.posix_spawnp",
        "posix.posix_spawnp",
        "os.fork",
        "posix.fork",
        "os.forkpty",
        "posix.forkpty",
        "subprocess.Popen",
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "_posixsubprocess.fork_exec",
        "pty.spawn",
        "pty.fork",
        "multiprocessing.Process.start",
        "nt.system",
        "nt.execv",
        "nt.execve",
        "nt.spawnv",
        "nt.spawnve",
        "os.startfile",
        "nt.startfile",
        "_winapi.CreateProcess",
    ),
    # os._exit/posix._exit are not listed: they terminate only the
    # calling process, run no code outside the patched interpreter and
    # touch no other process or resource — the normal way a program
    # ends, just skipping its own finalisers. The framework depends on
    # this call structurally to leave the sandboxed process, after
    # arming, as that process's final act (main_sandbox.py); requiring
    # an explicit ALLOW in every profile for the framework's own exit
    # would be a defect by omission, not a safeguard. os.abort stays
    # listed: same self-termination family, but it dumps core.
    "process-control": (
        "os.kill",
        "posix.kill",
        "os.killpg",
        "posix.killpg",
        "os.nice",
        "posix.nice",
        "os.setpriority",
        "posix.setpriority",
        "os.abort",
        "posix.abort",
        "os.setsid",
        "posix.setsid",
        "os.setpgid",
        "posix.setpgid",
        "os.setpgrp",
        "posix.setpgrp",
        # signal.signal/_signal.signal are not listed: registering a
        # handler is not emitting a signal. It installs a callback for a
        # signal aimed at the calling process, and grants no capability
        # sandboxed code lacks — it already runs arbitrary code. The
        # emitters stay listed (kill, killpg, raise_signal,
        # pthread_kill), as do the timers that emit (alarm, setitimer).
        # Residual gap, documented rather than fixed: remote/tools.py
        # set_pdeathsig() uses prctl(PR_SET_PDEATHSIG, SIGTERM), so
        # signal.signal(SIGTERM, SIG_IGN) lets a sandboxed process
        # outlive its parent. That is persistence, not a confinement
        # escape — the file, socket and env rules still hold — and it is
        # reachable anyway through a loop that never returns. Guarding
        # the registration was costing IPython, orderly shutdown and
        # alarm-based timeouts for that single case.
        "signal.alarm",
        "_signal.alarm",
        "signal.setitimer",
        "_signal.setitimer",
        "signal.raise_signal",
        "_signal.raise_signal",
        "signal.pthread_kill",
        "_signal.pthread_kill",
        "resource.setrlimit",
        "resource.prlimit",
        "nt.kill",
        "nt.abort",
    ),
    "privileges": (
        "os.setuid",
        "posix.setuid",
        "os.setgid",
        "posix.setgid",
        "os.seteuid",
        "posix.seteuid",
        "os.setegid",
        "posix.setegid",
        "os.setreuid",
        "posix.setreuid",
        "os.setregid",
        "posix.setregid",
        "os.setgroups",
        "posix.setgroups",
        # os.chroot / posix.chroot: not listed here. chroot is a
        # filesystem operation, and guard_files already patches both
        # names with a path check (_wrap_filename), which is strictly
        # stronger than this category's binary allow/deny.
        "os.umask",
        "posix.umask",
        "nt.umask",
    ),
    "threads": (
        "_thread.start_new_thread",
        "_thread.start_new",
        "_thread.start_joinable_thread",
        "threading._start_joinable_thread",
        "threading._start_new_thread",
        "threading.Thread.start",
        "_thread.interrupt_main",
        "threading.settrace",
        "threading.setprofile",
        "threading.stack_size",
        "_thread.stack_size",
    ),
    # ctypes.PyDLL is not listed: it inherits __init__ from ctypes.CDLL
    # without overriding it (measured: ``ctypes.PyDLL.__init__ is
    # ctypes.CDLL.__init__``), so patching ctypes.CDLL already guards
    # it. mmap.mmap and ctypes.memmove are not listed either: mmap.mmap
    # is an immutable C type whose __init__ cannot be patched, and
    # ctypes.memmove is a CFunctionType instance, not a class — wrapping
    # it in a plain function would drop its restype/argtypes/errcheck
    # configuration attributes. Both trade-offs are acceptable because
    # "native" is documented as detection and friction, not a barrier.
    "native": (
        "ctypes.CDLL",
        "ctypes.cast",
        "ctypes.string_at",
    ),
    # importlib.reload rebinds a module's attributes in place, on the very
    # module object every reference already holds: reloading ``os`` puts the
    # original C functions back over the ones guard_files patched, and every
    # later os.* call in the process runs unguarded. It is listed here rather
    # than under a module-system category of its own, which would add a
    # profile keyword for a single name; closing the sys.meta_path escape
    # will justify one.
    # Frame and heap inspection expose live references and locals. The
    # framework's eval wrapper still needs sys._getframe, so that one has a
    # narrow internal-module path in _wrap_frame_query.
    "introspection": (
        "importlib.reload",
        "sys._getframe",
        "sys._getframemodulename",
        "sys._current_frames",
        "sys._current_exceptions",
        "sys.settrace",
        "sys.setprofile",
        "sys.addaudithook",
        "gc.get_objects",
        "gc.get_referrers",
        "gc.get_referents",
        "inspect.currentframe",
        "inspect.stack",
        "inspect.trace",
        "faulthandler.enable",
    ),
    # Registered so python-api=ALLOW:dynamic-code stays an expressible escape
    # hatch, but patched by guard_eval rather than here: the guarded path
    # parses, validates and rewrites the source instead of answering a binary
    # allow/deny. Three names, not the six of the design spec: __import__ is
    # guard_import's, and code.compile_command / InteractiveInterpreter
    # .runsource reach these three anyway.
    "dynamic-code": (
        "builtins.eval",
        "builtins.exec",
        "builtins.compile",
    ),
    # A pickle stream is a program: its opcodes name a callable and call it, so
    # ``pickle.loads(b"cos\nsystem\n...")`` reaches ``os.system`` without
    # importing anything and without a source string guard_eval could parse.
    # Kept out of "dynamic-code", which _OWNED_ELSEWHERE hands to guard_eval
    # whole: an entry added there would never be patched at all.
    #
    # The ``_pickle`` twins are registered for the reason the os/posix twins
    # are: ``pickle.loads is _pickle.loads`` holds until one of them is
    # patched, so a table naming only ``pickle.*`` is walked around with one
    # ``import _pickle``.
    #
    # Residual gap, documented rather than fixed, like ctypes.pythonapi:
    # ``pickle.Unpickler`` is ``_pickle.Unpickler``, an immutable C type, so
    # neither its ``__init__`` nor its ``load`` can be patched -- and rebinding
    # the module name to a function would break subclassing, which is how a
    # restricted unpickler is written. ``Unpickler(fp).load()`` therefore stays
    # reachable; pinned as an xfail in tests/unit_tests/guard/test_guard_api.py.
    "deserialization": (
        "pickle.loads",
        "pickle.load",
        "_pickle.loads",
        "_pickle.load",
    ),
}

CATEGORIES: frozenset[str] = frozenset(SENSITIVE_API)

# The thread launch primitive moved between supported versions:
# 3.11-3.12 expose threading._start_new_thread, while 3.13 replaces it
# by threading._start_joinable_thread, the same object as
# _thread.start_joinable_thread. Both spellings are registered so a
# profile stays portable, and only the applicable ones are patched.
_PRE_313 = frozenset({"threading._start_new_thread"})
_FROM_313 = frozenset(
    {
        "threading._start_joinable_thread",
        "_thread.start_joinable_thread",
    }
)

# The C accelerator is not part of the language: an interpreter built without
# it, or a non-CPython one, exposes pickle's pure-Python implementation and no
# `_pickle` module at all. The twins are then absent rather than mistyped.
_NO_C_PICKLE = frozenset({"_pickle.loads", "_pickle.load"})

# Windows spells the os twin `nt`, not `posix`: there `os.system is nt.system`, so the
# posix twins alone leave `import nt; nt.system(...)` unguarded. subprocess reaches
# _winapi.CreateProcess there, as it reaches _posixsubprocess.fork_exec elsewhere.
_WINDOWS_ONLY = frozenset(
    {
        "nt.system",
        "nt.execv",
        "nt.execve",
        "nt.spawnv",
        "nt.spawnve",
        "os.startfile",
        "nt.startfile",
        "_winapi.CreateProcess",
        "nt.kill",
        "nt.abort",
        "nt.umask",
    }
)

# Absent from Windows: no posix module at all, and no fork, setuid, process group,
# rlimit, pty or alarm-style timer.
_POSIX_ONLY = frozenset(
    {qualname for qualnames in SENSITIVE_API.values() for qualname in qualnames if qualname.startswith("posix.")}
    | {
        "os.fork",
        "os.forkpty",
        "os.killpg",
        "os.nice",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.setegid",
        "os.seteuid",
        "os.setgid",
        "os.setgroups",
        "os.setpgid",
        "os.setpgrp",
        "os.setpriority",
        "os.setregid",
        "os.setreuid",
        "os.setsid",
        "os.setuid",
        "os.spawnlp",
        "os.spawnlpe",
        "os.spawnvp",
        "os.spawnvpe",
        "_posixsubprocess.fork_exec",
        "pty.fork",
        "pty.spawn",
        "resource.prlimit",
        "resource.setrlimit",
        "signal.alarm",
        "_signal.alarm",
        "signal.pthread_kill",
        "_signal.pthread_kill",
        "signal.setitimer",
        "_signal.setitimer",
    }
)

# Linux only: macOS has no prlimit.
_LINUX_ONLY = frozenset({"resource.prlimit"})

_INTROSPECTION_VERSION_OPTIONAL = frozenset({"sys._getframemodulename", "sys._current_exceptions"})
# sys._getframemodulename appeared in Python 3.12.
_FROM_312 = frozenset({"sys._getframemodulename"})

OPTIONAL: frozenset[str] = (
    _PRE_313 | _FROM_313 | _NO_C_PICKLE | _WINDOWS_ONLY | _POSIX_ONLY | _LINUX_ONLY | _INTROSPECTION_VERSION_OPTIONAL
)
"""Entries whose absence is legitimate on some version or platform.

The integrity test fails on a missing entry unless it is listed here, so
a typo is still caught while a version difference is not a false alarm.
"""


def _not_applicable() -> frozenset[str]:
    """Return the entries this interpreter must not patch.

    ``guard_import._apply_patch`` calls ``getattr`` before invoking the
    factory, so a registered name absent from a module that *is*
    imported would raise at startup: ``threading`` across versions, and
    ``os`` across platforms. A module that cannot be imported at all is
    never patched.
    """
    version = _PRE_313 if sys.version_info >= (3, 13) else _FROM_313
    platform = _POSIX_ONLY if sys.platform == "win32" else _WINDOWS_ONLY
    linux = frozenset() if sys.platform == "linux" else _LINUX_ONLY
    introspection = frozenset() if sys.version_info >= (3, 12) else _FROM_312
    return version | platform | linux | introspection


_CATEGORY_OF: dict[str, str] = {
    qualname: category for category, qualnames in SENSITIVE_API.items() for qualname in qualnames
}


def all_qualnames() -> tuple[str, ...]:
    """Return every qualified name of the registry, in category order."""
    return tuple(_CATEGORY_OF)


def split_qualname(qualname: str) -> tuple[str, str]:
    """Split ``module.attr`` into its module and its attribute path.

    ``"threading.Thread.start"`` yields ``("threading",
    "Thread.start")``. The module is always the leading segment, matching
    ``guard_import._conv_patch_rules``.
    """
    module_name, _, attribute_path = qualname.partition(".")
    return module_name, attribute_path


_PREFIX = "python-api="
_ACTIONS = {"ALLOW": True, "DENY": False}


class ApiRule(NamedTuple):
    """One parsed ``python-api=`` target."""

    allow: bool
    target: str
    is_category: bool
    config: ConfigLine


ApiRules = tuple[ApiRule, ...]


def _add_error(errors: list[ErrorMsg], rule: ConfigLine, detail: str) -> None:
    errors.append(
        (
            f"{format_ruleref(rule)}: In {rule.rule!r}, {detail}",
            rule.path,
            rule.ln,
        )
    )


def parse_rules(
    config: ConfigLines,
    errors: list[ErrorMsg],
) -> tuple[ApiRules, ConfigLines]:
    """Consume ``python-api=`` lines and return the other lines.

    Unknown categories and unknown functions are configuration errors:
    a typo must fail at startup rather than silently leave a hole.
    """
    parsed: list[ApiRule] = []
    others: ConfigLines = []
    for rule in config:
        if not rule.rule.startswith(_PREFIX):
            others.append(rule)
            continue
        value = rule.rule[len(_PREFIX) :].strip()
        action, sep, targets = value.partition(":")
        if not sep:
            _add_error(
                errors,
                rule,
                "expected the form 'ACTION:target', " f"with ACTION in {sorted(_ACTIONS)}.",
            )
            continue
        if action.strip() not in _ACTIONS:
            _add_error(
                errors,
                rule,
                f"unknown action {action.strip()!r}, " f"expected one of {sorted(_ACTIONS)}.",
            )
            continue
        allow = _ACTIONS[action.strip()]
        line_rules: list[ApiRule] = []
        failed = False
        for target in targets.split(","):
            target = target.strip()
            if not target:
                _add_error(errors, rule, "empty target.")
                failed = True
                break
            if target.upper() in _ACTIONS or ":" in target:
                _add_error(
                    errors,
                    rule,
                    "one action per line: do not mix ALLOW and DENY.",
                )
                failed = True
                break
            if target == "*":
                line_rules.append(ApiRule(allow, "*", False, rule))
                continue
            is_category = "." not in target
            if is_category and target not in CATEGORIES:
                _add_error(
                    errors,
                    rule,
                    f"unknown category {target!r}, " f"expected one of {sorted(CATEGORIES)}.",
                )
                failed = True
                break
            if not is_category and target not in _CATEGORY_OF:
                _add_error(
                    errors,
                    rule,
                    f"{target!r} is not a registered sensitive " "function.",
                )
                failed = True
                break
            line_rules.append(ApiRule(allow, target, is_category, rule))
        if not failed:
            parsed.extend(line_rules)
    return tuple(parsed), others


_allowed: ImmutableDict[str, bool] = ImmutableDict({})


def activate_guard(rules: ApiRules) -> None:
    """Flatten the rules into a decision per registered function.

    Resolution is by specificity, not by order: a function rule beats a
    category rule wherever it sits, which keeps ``include`` composition
    predictable. ``DENY`` wins at equal specificity.
    """
    global _allowed
    decisions: dict[str, bool] = {q: False for q in all_qualnames()}
    wildcard = [r for r in rules if r.target == "*"]
    if wildcard:
        value = all(r.allow for r in wildcard)
        decisions = {q: value for q in decisions}
    cats: dict[str, bool] = {}
    for rule in rules:
        if rule.is_category:
            cats[rule.target] = rule.allow and cats.get(rule.target, True)
    for qualname in decisions:
        category = _CATEGORY_OF[qualname]
        if category in cats:
            decisions[qualname] = cats[category]
    funcs: dict[str, bool] = {}
    for rule in rules:
        if not rule.is_category and rule.target != "*":
            funcs[rule.target] = rule.allow and funcs.get(rule.target, True)
    decisions.update(funcs)
    _allowed = ImmutableDict(decisions)
    logger.debug(
        "guard_api: %d/%d sensitive functions allowed",
        sum(_allowed.values()),
        len(_allowed),
    )


def is_allowed(qualname: str) -> bool:
    """Return whether a registered function may be called."""
    return _allowed.get(qualname, False)


class LearnApiRule(NamedTuple):
    """One sensitive call observed in learning mode."""

    qualname: str


_WARN_CATEGORIES = (
    "process-exec",
    "privileges",
    "native",
    "dynamic-code",
    "deserialization",
)

_CATEGORY_HELP: dict[str, str] = {
    "process-exec": "runs code outside the patched interpreter",
    "process-control": "kills processes, exhausts host resources",
    "privileges": "changes process identity or root",
    "threads": "concurrency primitives",
    "native": "native code and arbitrary memory access",
    "introspection": "can be used to undo the patches",
    "dynamic-code": "runs code built at runtime from a string, unguarded",
    "deserialization": "runs the callables a byte stream names, unguarded",
}


def generate_rules(learn: set[Any]) -> list[str]:
    """Emit ``python-api=`` lines for the calls seen in learning mode.

    The category is inferred here, not recorded at call time: an
    observed call only knows which function it reached. When the union
    of the already-allowed functions and the learned ones covers a
    category, a single category line is emitted instead of the function
    lines; the two forms are never mixed.
    """
    names = {r.qualname for r in learn if isinstance(r, LearnApiRule)}
    if not names:
        return []
    by_cat: dict[str, list[str]] = {}
    for name in sorted(names):
        by_cat.setdefault(_CATEGORY_OF[name], []).append(name)
    skip = _not_applicable()
    lines: list[str] = []
    for cat in SENSITIVE_API:
        if cat not in by_cat:
            continue
        mark = "# ⚠ " if cat in _WARN_CATEGORIES else "# "
        lines.append(f"{mark}{cat}: {_CATEGORY_HELP[cat]}")
        entries = [q for q in SENSITIVE_API[cat] if q not in skip]
        covered = {q for q in entries if is_allowed(q) or q in by_cat[cat]}
        if covered == set(entries):
            lines.append(f"python-api=ALLOW:{cat}")
        else:
            lines.extend(f"python-api=ALLOW:{q}" for q in by_cat[cat])
    return lines


def _wrap_guarded(func: Callable[..., Any], *, qualname: str, category: str) -> Callable[..., Any]:
    """Wrap a sensitive function with the guard's control point."""
    if getattr(func, "__pysandbox_api__", False):
        return func

    if qualname in {"sys._getframe", "sys._getframemodulename"}:
        return _wrap_frame_query(func, qualname=qualname, category=category)

    @guard_wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not _lc_is_armed():
            return func(*args, **kwargs)
        if is_learning_mode():
            if not is_allowed(qualname):
                add_learning_rule(LearnApiRule(qualname))
            return func(*args, **kwargs)
        if not is_allowed(qualname):
            raise RuleApiPermissionError(qualname, category)
        return func(*args, **kwargs)

    wrapper.__pysandbox_api__ = True  # type: ignore[attr-defined]
    return wrapper


def _wrap_frame_query(func: Callable[..., Any], *, qualname: str, category: str) -> Callable[..., Any]:
    """Guard a frame query while preserving its depth and framework use."""

    @guard_wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        armed = _lc_is_armed()
        internal = False
        if armed and qualname == "sys._getframe":
            caller = func(1)
            module_name = caller.f_globals.get("__name__")
            module = sys.modules.get(module_name) if isinstance(module_name, str) else None
            internal = (
                isinstance(module_name, str)
                and module_name.startswith("pysandboxes.")
                and getattr(module, "__dict__", None) is caller.f_globals
            )
        if armed and not internal:
            if is_learning_mode():
                if not is_allowed(qualname):
                    add_learning_rule(LearnApiRule(qualname))
            elif not is_allowed(qualname):
                raise RuleApiPermissionError(qualname, category)
        if qualname == "sys._getframe":
            if kwargs or len(args) > 1:
                return func(*args, **kwargs)
            depth = args[0] if args else 0
        else:
            if len(args) > 1 or (args and "depth" in kwargs):
                return func(*args, **kwargs)
            depth = args[0] if args else kwargs.pop("depth", 0)
            if kwargs:
                return func(*args, **kwargs)
        return func(depth + 1)

    wrapper.__pysandbox_api__ = True  # type: ignore[attr-defined]
    return wrapper


# A handful of registry names are classes, not functions: patching them
# directly would replace the class with a plain function, breaking
# isinstance/issubclass/subclassing for every caller, allowed or not.
# The fix is to patch their __init__ instead, which mutates the class
# rather than replacing it. The registry name stays the public,
# documented target; only the patch table's key moves.
#
# Residual gap, documented rather than fixed: ctypes.pythonapi is a
# ctypes.PyDLL *instance* built at import time, so using it calls no
# __init__ and is never guarded.
_PATCH_TARGET: dict[str, str] = {
    "subprocess.Popen": "subprocess.Popen.__init__",
    "ctypes.CDLL": "ctypes.CDLL.__init__",
}

# guard_eval patches these three itself: the guarded path parses and rewrites
# the source, which a binary allow/deny cannot express. Deliberately NOT
# folded into _not_applicable(): that set is also subtracted in
# generate_rules(), and learning must keep emitting a dynamic-code line.
_OWNED_ELSEWHERE = frozenset(SENSITIVE_API["dynamic-code"])


def patch_rules(learn: bool) -> dict[str, Callable[..., Any]]:
    """Return the patch table for every registered function.

    Every entry is patched, allowed or not: the rules are not known
    yet when this is called (``py_sandbox.activate_sandboxes`` fills
    them afterwards), and the decision is a dict lookup at call time.
    """
    del learn
    skip = _not_applicable()
    return {
        _PATCH_TARGET.get(qualname, qualname): _f(
            _wrap_guarded,
            qualname=qualname,
            category=category,
        )
        for qualname, category in _CATEGORY_OF.items()
        if qualname not in skip and qualname not in _OWNED_ELSEWHERE
    }


if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:

    def _deactivate_guard_api() -> None:
        """Reset the guard between tests.

        The armed flag is not reset here: it belongs to :mod:`.lifecycle`,
        which resets it in ``_reset_for_tests()``.
        """
        global _allowed
        _allowed = ImmutableDict({})
