# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Namespace construction, graded warnings, execution and learning."""

import logging
import os
from typing import Any, Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes.eval_rules import DEFAULT_RULES, NameSet
from pysandboxes.guard_eval import (
    CAPABILITY_BUILTINS,
    STRONG_MODULES,
    _reset_context_warnings,
    build_namespace,
    classify_context_value,
    warn_about_context,
)


def _names(*allowed: str) -> NameSet:
    return NameSet(allow=frozenset(allowed), allow_patterns=(), deny=frozenset(), deny_patterns=())


@pytest.fixture(autouse=True)
def _fresh() -> Iterator[None]:
    _reset_context_warnings()
    yield
    _reset_context_warnings()


def test_a_caller_context_with_builtins_is_honoured_untouched() -> None:
    rules = DEFAULT_RULES._replace(declared=True, call=_names("len"))
    caller: dict[str, Any] = {"__builtins__": {}}
    namespace = build_namespace(rules, caller_globals=caller, names=None, from_wrapper=False)
    assert namespace is caller
    assert namespace["__builtins__"] == {}


def test_a_caller_context_without_builtins_gets_them_from_eval_call() -> None:
    """CPython would inject all 159; the wrapper fills the key instead."""
    rules = DEFAULT_RULES._replace(declared=True, call=_names("len"))
    caller = {"helper": len}
    namespace = build_namespace(rules, caller_globals=caller, names=None, from_wrapper=False)
    assert set(namespace["__builtins__"]) == {"len"}
    assert "open" not in namespace["__builtins__"]
    assert namespace["helper"] is len


def test_no_caller_globals_builds_the_namespace_from_eval_call() -> None:
    rules = DEFAULT_RULES._replace(declared=True, call=_names("len", "range"))
    namespace = build_namespace(rules, caller_globals=None, names=None, from_wrapper=False)
    assert set(namespace["__builtins__"]) == {"len", "range"}


def test_an_empty_eval_call_yields_an_empty_builtins() -> None:
    rules = DEFAULT_RULES._replace(declared=True)
    namespace = build_namespace(rules, caller_globals=None, names=None, from_wrapper=False)
    assert namespace["__builtins__"] == {}


def test_the_helpers_are_always_bound() -> None:
    rules = DEFAULT_RULES._replace(declared=True)
    namespace = build_namespace(rules, caller_globals=None, names=None, from_wrapper=False)
    assert "__sb_getattr__" in namespace
    assert "__sb_tick__" in namespace


def test_the_helpers_are_not_reachable_through_eval_call() -> None:
    rules = DEFAULT_RULES._replace(declared=True, call=_names("len"))
    namespace = build_namespace(rules, caller_globals=None, names=None, from_wrapper=False)
    assert "__sb_getattr__" not in namespace["__builtins__"]


def test_closed_ignores_the_caller_context() -> None:
    rules = DEFAULT_RULES._replace(declared=True, namespace="closed", call=_names("len"))
    namespace = build_namespace(rules, caller_globals={"secret": 1}, names=None, from_wrapper=False)
    assert "secret" not in namespace
    assert set(namespace["__builtins__"]) == {"len"}


def test_caller_mode_never_reaches_build_namespace() -> None:
    """It is a wrapper-level short circuit: rewritten code needs the helpers."""
    rules = DEFAULT_RULES._replace(declared=True, namespace="caller", call=_names("len"))
    namespace = build_namespace(rules, caller_globals={"helper": len}, names=None, from_wrapper=False)
    assert "__sb_getattr__" in namespace


def test_the_wrapper_never_takes_the_adaptive_branch() -> None:
    """guarded_eval's names are wrapper-supplied data, not a caller context."""
    rules = DEFAULT_RULES._replace(declared=True, call=_names("len"))
    namespace = build_namespace(
        rules,
        caller_globals={"secret": 1},
        names={"data": [1, 2]},
        from_wrapper=True,
    )
    assert "secret" not in namespace
    assert namespace["data"] == [1, 2]
    assert set(namespace["__builtins__"]) == {"len"}


def test_a_module_is_a_strong_finding() -> None:
    assert classify_context_value(os) == "strong"


def test_a_capability_builtin_is_a_strong_finding() -> None:
    """A six-name sample. `test_every_capability_builtin_is_graded_strong` is
    the one that binds: a sample this size passed while `open` was weak."""
    import builtins

    for name in ("getattr", "open", "eval", "type", "vars", "dir"):
        assert name in CAPABILITY_BUILTINS
        assert classify_context_value(getattr(builtins, name)) == "strong"


def test_every_capability_builtin_is_graded_strong() -> None:
    """The whole set, not a sample: `open` was graded weak by a name-and-module
    test because `open.__module__` is `_io`, and a six-name sample happened to
    cover it only by luck."""
    import builtins

    for name in CAPABILITY_BUILTINS:
        if hasattr(builtins, name):
            assert classify_context_value(getattr(builtins, name)) == "strong", name


def test_a_patched_capability_builtin_is_still_strong() -> None:
    """The grade must survive arming, which is when it matters most.

    The other guards replace `builtins.open` when they arm, so a
    classification keyed on the identity of an object captured at import time
    silently stops recognising the very builtin it was written for. This test
    runs with the guards armed by the conftest, which is what caught it.
    """
    import builtins

    assert classify_context_value(builtins.open) == "strong"


def test_a_callable_from_a_strong_module_is_a_strong_finding() -> None:
    assert classify_context_value(os.listdir) == "strong"


def test_a_c_implemented_callable_is_graded_by_its_real_module() -> None:
    """`__module__` names where a callable was defined, not where it is reached.

    `os.listdir` reports `posix`, so listing the `os` facade alone would grade
    the real capability weak. `_socket.socket` is a distinct object from
    `socket.socket` and reports `_socket`.
    """
    import _socket

    assert os.listdir.__module__ in STRONG_MODULES
    assert classify_context_value(os.listdir) == "strong"
    assert classify_context_value(os.system) == "strong"
    assert classify_context_value(_socket.socket) == "strong"


def test_the_facade_modules_need_no_implementation_twin() -> None:
    """Measured, not assumed: only `os` delegates to a differently-named module.

    This is the check that would catch a future CPython moving one of these
    into a private module, which is how `os.listdir` slipped through as weak.
    """
    import ctypes
    import importlib
    import socket
    import subprocess

    for callable_under_test in (subprocess.run, importlib.import_module, ctypes.CDLL, socket.socket):
        assert classify_context_value(callable_under_test) == "strong", callable_under_test


def test_an_ordinary_callable_is_a_weak_finding() -> None:
    assert classify_context_value(lambda: None) == "weak"


def test_an_ordinary_instance_is_a_weak_finding() -> None:
    class Thing:
        pass

    assert classify_context_value(Thing()) == "weak"


def test_scalars_and_containers_of_scalars_produce_nothing() -> None:
    for value in (1, "a", 1.5, None, True, [1, 2], {"a": 1}, (1, 2), {1, 2}):
        assert classify_context_value(value) == ""


def test_a_module_in_the_context_is_logged_with_its_acknowledgement_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING", logger="pysandboxes.guard_eval"):
        warn_about_context({"os": os}, "tools.py:66")
    logged = " ".join(record.getMessage() for record in caplog.records)
    assert "module 'os'" in logged
    assert "tools.py:66" in logged
    assert "eval-call=os" in logged
    assert "eval-namespace=closed" in logged


def test_findings_are_deduplicated_by_call_site_and_name(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="pysandboxes.guard_eval"):
        for _ in range(1000):
            warn_about_context({"os": os}, "tools.py:66")
    assert len(caplog.records) == 1


def test_the_same_name_at_another_call_site_is_logged_again(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="pysandboxes.guard_eval"):
        warn_about_context({"os": os}, "tools.py:66")
        warn_about_context({"os": os}, "other.py:12")
    assert len(caplog.records) == 2


def test_a_scalar_context_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="pysandboxes.guard_eval"):
        warn_about_context({"x": 1, "rows": [1, 2, 3]}, "tools.py:66")
    assert not caplog.records


def test_the_finding_names_the_application_call_site() -> None:
    """The call site is carried in the message, not inferred from the stack.

    A logger has no `stacklevel` story the way `warnings.warn` did: whatever
    frame emits the record is what `%(pathname)s` would show. So `source_ref`
    -- which the wrapper already builds from the caller's frame -- is what
    tells the reader which line of their application passed `os`.
    """

    class _Collect(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.messages: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.messages.append(record.getMessage())

    handler = _Collect()
    logger_under_test = logging.getLogger("pysandboxes.guard_eval")
    logger_under_test.addHandler(handler)
    try:
        warn_about_context({"os": os}, "app.py:3")
    finally:
        logger_under_test.removeHandler(handler)
    assert any("app.py:3" in message for message in handler.messages)


def test_builtins_is_never_itself_reported(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="pysandboxes.guard_eval"):
        warn_about_context({"__builtins__": {}}, "tools.py:66")
    assert not caplog.records
