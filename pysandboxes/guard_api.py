# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Guard denying calls to sensitive functions.

Import rights and call rights are distinct: a module may be importable
while some of its functions must stay unreachable. This guard denies
calls to a finite registry of sensitive functions, independently of
``python-import=``, and records attempted calls in learning mode.
"""

import functools
import logging
import os
import sys
from typing import Any, Callable, NamedTuple

from .e import RuleApiPermissionError
from .immutable_dict import ImmutableDict
from .learning import add_learning_rule, is_learning_mode
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
    ),
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
        "os._exit",
        "posix._exit",
        "os.setsid",
        "posix.setsid",
        "os.setpgid",
        "posix.setpgid",
        "os.setpgrp",
        "posix.setpgrp",
        "signal.signal",
        "_signal.signal",
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
        "os.chroot",
        "posix.chroot",
        "os.umask",
        "posix.umask",
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
    "native": (
        "ctypes.CDLL",
        "ctypes.PyDLL",
        "ctypes.memmove",
        "ctypes.cast",
        "ctypes.string_at",
        "mmap.mmap",
    ),
    "introspection": (
        "sys.settrace",
        "sys.setprofile",
        "sys.addaudithook",
        "gc.get_objects",
        "gc.get_referrers",
        "faulthandler.enable",
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

OPTIONAL: frozenset[str] = _PRE_313 | _FROM_313
"""Entries whose absence is legitimate on some version or platform.

The integrity test fails on a missing entry unless it is listed here, so
a typo is still caught while a version difference is not a false alarm.
"""


def _not_applicable() -> frozenset[str]:
    """Return the entries this interpreter must not patch.

    ``guard_import._apply_patch`` calls ``getattr`` before invoking the
    factory, so a registered name absent from a module that *is*
    imported would raise at startup. Only ``threading`` is concerned:
    a module that cannot be imported at all is never patched.
    """
    if sys.version_info >= (3, 13):
        return _PRE_313
    return _FROM_313


_CATEGORY_OF: dict[str, str] = {
    qualname: category
    for category, qualnames in SENSITIVE_API.items()
    for qualname in qualnames
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


def _error(errors: list[ErrorMsg], rule: ConfigLine, detail: str) -> None:
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
            _error(
                errors,
                rule,
                "expected the form 'ACTION:target', "
                f"with ACTION in {sorted(_ACTIONS)}.",
            )
            continue
        if action.strip() not in _ACTIONS:
            _error(
                errors,
                rule,
                f"unknown action {action.strip()!r}, "
                f"expected one of {sorted(_ACTIONS)}.",
            )
            continue
        allow = _ACTIONS[action.strip()]
        line_rules: list[ApiRule] = []
        failed = False
        for target in targets.split(","):
            target = target.strip()
            if not target:
                _error(errors, rule, "empty target.")
                failed = True
                break
            if target.upper() in _ACTIONS or ":" in target:
                _error(
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
                _error(
                    errors,
                    rule,
                    f"unknown category {target!r}, "
                    f"expected one of {sorted(CATEGORIES)}.",
                )
                failed = True
                break
            if not is_category and target not in _CATEGORY_OF:
                _error(
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


_rules: ApiRules = ()
_allowed: ImmutableDict[str, bool] = ImmutableDict({})
_armed: bool = False


def activate_guard(rules: ApiRules) -> None:
    """Flatten the rules into a decision per registered function.

    Resolution is by specificity, not by order: a function rule beats a
    category rule wherever it sits, which keeps ``include`` composition
    predictable. ``DENY`` wins at equal specificity.
    """
    global _rules, _allowed
    _rules = rules
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


def arm() -> None:
    """Start enforcing, just before user code takes over.

    Framework code runs while the guard is disarmed, so it needs no
    exemption and no escape hatch. Idempotent: every entry point may
    call it.
    """
    global _armed
    if not _armed:
        logger.debug("guard_api: armed")
    _armed = True


def is_armed() -> bool:
    """Return whether the guard is enforcing."""
    return _armed


def _wrap_guarded(
    func: Callable[..., Any], *, qualname: str, category: str
) -> Callable[..., Any]:
    """Wrap a sensitive function with the guard's control point."""
    if getattr(func, "__pysandbox_api__", False):
        return func

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        if not _armed:
            return func(*args, **kwargs)
        if is_learning_mode():
            if not _allowed.get(qualname, False):
                add_learning_rule(LearnApiRule(qualname))
            return func(*args, **kwargs)
        if not _allowed.get(qualname, False):
            raise RuleApiPermissionError(qualname, category)
        return func(*args, **kwargs)

    wrapper.__pysandbox_api__ = True  # type: ignore[attr-defined]
    return wrapper


def patch_rules(learn: bool) -> dict[str, Callable[..., Any]]:
    """Return the patch table for every registered function.

    Every entry is patched, allowed or not: the rules are not known
    yet when this is called (``py_sandbox.activate_sandboxes`` fills
    them afterwards), and the decision is a dict lookup at call time.
    """
    del learn
    skip = _not_applicable()
    return {
        qualname: _f(
            _wrap_guarded,
            qualname=qualname,
            category=category,
        )
        for qualname, category in _CATEGORY_OF.items()
        if qualname not in skip
    }


if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:

    def _deactivate_guard_api() -> None:
        """Reset the guard between tests."""
        global _rules, _allowed, _armed
        _rules = ()
        _allowed = ImmutableDict({})
        _armed = False
