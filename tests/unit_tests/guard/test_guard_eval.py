# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Namespace construction, graded warnings, execution and learning."""

import builtins
import logging
import os
import pathlib
import sysconfig
import time
import types
from typing import Any, Callable, Iterator

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import EvalInterrupted, EvalSyntaxRejected, SandBoxError
from pysandboxes.eval_rules import CORE_NODES, DEFAULT_RULES, SYNTAX_GROUPS, NameSet
from pysandboxes.guard_eval import (
    CAPABILITY_BUILTINS,
    STRONG_MODULES,
    TAG_PREFIX,
    _deactivate_guard_eval,
    _reset_context_warnings,
    activate_guard,
    build_namespace,
    classify_context_value,
    guarded_eval,
    leaked_threads,
    resolve_profile,
    warn_about_context,
)
from pysandboxes.guard_api import SENSITIVE_API, _deactivate_guard_api
from pysandboxes.guard_api import activate_guard as activate_api
from pysandboxes.guard_api import arm as arm_api
from pysandboxes.guard_api import parse_rules as parse_api_rules
from pysandboxes.guard_eval import is_ambient, patch_rules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.sb_types import ConfigLine


def _names(*allowed: str) -> NameSet:
    return NameSet(allow=frozenset(allowed), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _frame_with(filename: str) -> types.FrameType:
    """Build a real frame whose code object carries `filename`."""
    namespace: dict[str, object] = {}
    exec(compile("def probe():\n    import sys\n    return sys._getframe()", filename, "exec"), namespace)  # noqa: S102
    return namespace["probe"]()  # type: ignore[operator,no-any-return]


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


def _syntax(*groups: str) -> NameSet:
    nodes = set(CORE_NODES)
    for group in groups:
        nodes.update(SYNTAX_GROUPS[group])
    return NameSet(allow=frozenset(nodes), allow_patterns=(), deny=frozenset(), deny_patterns=())


def _activate(**kwargs: object) -> None:
    rules = DEFAULT_RULES._replace(declared=True, **kwargs)  # type: ignore[arg-type]
    activate_guard(ImmutableDict({"": rules}))


@pytest.fixture(autouse=True)
def _clean_guard() -> Iterator[None]:
    yield
    _deactivate_guard_eval()


def test_a_calculator_profile_evaluates_arithmetic() -> None:
    _activate(syntax=_syntax("arith"), namespace="closed")
    assert guarded_eval("40 + 2") == 42


def test_a_refused_construct_raises_with_the_full_report() -> None:
    _activate(syntax=_syntax("arith"), namespace="closed")
    with pytest.raises(EvalSyntaxRejected) as caught:
        guarded_eval("[x for x in ()]")
    assert "eval-syntax=comprehension" in str(caught.value)


def test_a_native_syntax_error_propagates_as_itself() -> None:
    _activate(syntax=_syntax("arith"), namespace="closed")
    with pytest.raises(SyntaxError) as caught:
        guarded_eval("1 +")
    assert not isinstance(caught.value, EvalSyntaxRejected)


def test_names_are_merged_into_the_namespace() -> None:
    _activate(syntax=_syntax("arith"), namespace="closed")
    assert guarded_eval("data + 1", names={"data": 41}) == 42


def test_an_unknown_profile_is_an_error_not_a_silent_fallback() -> None:
    _activate(syntax=_syntax("arith"))
    with pytest.raises(ValueError, match="llm"):
        resolve_profile("llm")


def test_a_known_profile_resolves() -> None:
    activate_guard(
        ImmutableDict(
            {
                "": DEFAULT_RULES._replace(declared=True, timeout=5.0),
                "llm": DEFAULT_RULES._replace(declared=True, timeout=2.0),
            }
        )
    )
    assert resolve_profile("llm").timeout == 2.0


def test_a_timeout_interrupts_the_evaluation() -> None:
    _activate(syntax=_syntax("loop"), namespace="closed", timeout=0.3, max_iterations=10**9)
    started = time.monotonic()
    with pytest.raises(EvalInterrupted, match="eval-timeout"):
        guarded_eval("while True:\n    pass", mode="exec")
    assert time.monotonic() - started < 3.0


def test_a_timeout_actually_kills_the_worker_thread() -> None:
    """A thread-local flag would leave the worker spinning forever (D4)."""
    _activate(syntax=_syntax("loop"), namespace="closed", timeout=0.3, max_iterations=10**9)
    before = leaked_threads()
    with pytest.raises(EvalInterrupted):
        guarded_eval("while True:\n    pass", mode="exec")
    time.sleep(0.5)
    assert leaked_threads() == before


def test_the_iteration_budget_interrupts_a_loop() -> None:
    _activate(syntax=_syntax("loop"), namespace="closed", max_iterations=100, timeout=30.0)
    with pytest.raises(EvalInterrupted, match="eval-max-iterations=100"):
        guarded_eval("while True:\n    pass", mode="exec")


def test_an_interruption_is_not_catchable_from_inside() -> None:
    """EvalInterrupted derives from BaseException only, on purpose."""
    _activate(
        syntax=_syntax("loop", "exception"),
        namespace="closed",
        max_iterations=50,
        timeout=30.0,
    )
    source = "while True:\n    try:\n        pass\n    except Exception:\n        pass"
    with pytest.raises(EvalInterrupted):
        guarded_eval(source, mode="exec")


def test_except_sandbox_error_does_not_catch_a_timeout() -> None:
    _activate(syntax=_syntax("loop"), namespace="closed", max_iterations=10, timeout=30.0)
    with pytest.raises(EvalInterrupted):
        try:
            guarded_eval("while True:\n    pass", mode="exec")
        except SandBoxError:  # pragma: no cover - must not fire
            pytest.fail("SandBoxError caught an EvalInterrupted")


def test_an_exception_from_inside_reaches_the_caller() -> None:
    _activate(syntax=_syntax("arith"), namespace="closed", call=_names("int"))
    with pytest.raises(ValueError):
        guarded_eval("int('zz')")


def test_the_worker_frame_is_absent_from_the_traceback() -> None:
    """The call looks synchronous, so its traceback must read that way.

    The exception is raised in another thread and carries that thread's
    traceback across. Without the elision, `_worker` -- a frame the caller
    never wrote -- sits between the caller and the evaluated line.

    The assertion matches the rendered frame line, `, in _worker\\n`, and not
    the bare name: a traceback also renders the frames of this test and of
    `_reraise_from_worker`, both of which contain `_worker` as a substring, so
    a substring check would fail while the elision worked.
    """
    import traceback as traceback_module

    _activate(syntax=_syntax("arith"), namespace="closed", call=_names("int"))
    with pytest.raises(ValueError) as caught:
        guarded_eval("int('zz')")
    rendered = "".join(traceback_module.format_tb(caught.value.__traceback__))
    assert ", in _worker\n" not in rendered
    assert "<eval:" in rendered


def test_a_timeout_points_at_the_line_that_was_running() -> None:
    """EvalInterrupted crosses the same boundary as any other exception."""
    _activate(syntax=_syntax("loop"), namespace="closed", timeout=0.3, max_iterations=10**9)
    with pytest.raises(EvalInterrupted) as caught:
        guarded_eval("while True:\n    pass", mode="exec")
    assert caught.value.__traceback__ is not None


def test_the_source_ref_carries_the_profile_name() -> None:
    activate_guard(ImmutableDict({"llm": DEFAULT_RULES._replace(declared=True, syntax=_syntax())}))
    with pytest.raises(EvalSyntaxRejected, match=r"<eval:llm>"):
        guarded_eval("1 + 1", profile="llm")


def test_the_tag_prefix_is_what_compile_stamps() -> None:
    assert TAG_PREFIX == "<eval:"


def _patched() -> dict[str, Callable[..., Any]]:
    """Apply the guard_eval patch table to a throwaway namespace.

    Typed as callables rather than `object`, so the calls below need no
    `# type: ignore[operator]`: the table's values are what `patch_rules`
    already declares them to be.
    """
    return {name: factory(getattr(builtins, name.split(".")[1])) for name, factory in patch_rules(False).items()}


def test_dynamic_code_holds_exactly_three_names() -> None:
    assert SENSITIVE_API["dynamic-code"] == ("builtins.eval", "builtins.exec", "builtins.compile")


def test_dynamic_code_is_an_accepted_python_api_target() -> None:
    errors: list[object] = []
    rules, others = parse_api_rules(
        [ConfigLine("python-api=ALLOW:dynamic-code", pathlib.Path("p"), 0)],
        errors,  # type: ignore[arg-type]
    )
    assert not errors
    assert rules and rules[0].target == "dynamic-code"


def test_guard_api_does_not_patch_the_three_builtins() -> None:
    from pysandboxes.guard_api import patch_rules as api_patch_rules

    table = api_patch_rules(False)
    assert not [key for key in table if key.startswith("builtins.")]


def test_guard_eval_patches_exactly_the_three_builtins() -> None:
    assert set(patch_rules(False)) == {"builtins.eval", "builtins.exec", "builtins.compile"}


def test_an_unarmed_call_reaches_the_raw_builtin() -> None:
    _deactivate_guard_api()
    patched_eval = _patched()["builtins.eval"]
    assert patched_eval("1 + 1") == 2


def test_an_unarmed_bare_eval_still_sees_the_callers_locals() -> None:
    """The wrapper is a frame between eval and its caller; it must not show."""
    _deactivate_guard_api()
    patched_eval = _patched()["builtins.eval"]
    local_value = 41  # noqa: F841 - read by the evaluated source, which is the point
    assert patched_eval("local_value + 1") == 42


def test_an_armed_call_without_any_eval_key_is_refused() -> None:
    from pysandboxes.e import RuleApiPermissionError

    _deactivate_guard_api()
    activate_api(())
    arm_api()
    activate_guard(ImmutableDict({}))
    patched_eval = _patched()["builtins.eval"]
    try:
        with pytest.raises(RuleApiPermissionError, match="dynamic-code"):
            patched_eval("1 + 1")
    finally:
        _deactivate_guard_api()


def test_allow_dynamic_code_beats_a_declared_profile() -> None:
    _deactivate_guard_api()
    errors: list[object] = []
    rules, _ = parse_api_rules(
        [ConfigLine("python-api=ALLOW:dynamic-code", pathlib.Path("p"), 0)],
        errors,  # type: ignore[arg-type]
    )
    activate_api(rules)
    arm_api()
    _activate(syntax=_syntax(), namespace="closed")
    patched_eval = _patched()["builtins.eval"]
    try:
        assert patched_eval("1 + 1") == 2
    finally:
        _deactivate_guard_api()


def test_a_declared_profile_guards_an_armed_call() -> None:
    _deactivate_guard_api()
    activate_api(())
    arm_api()
    _activate(syntax=_syntax("arith"), namespace="closed")
    patched_eval = _patched()["builtins.eval"]
    try:
        assert patched_eval("40 + 2", {"__builtins__": {}}, {}) == 42
        with pytest.raises(EvalSyntaxRejected):
            patched_eval("[x for x in ()]", {"__builtins__": {}}, {})
    finally:
        _deactivate_guard_api()


def test_a_stdlib_caller_is_ambient() -> None:
    stdlib = pathlib.Path(sysconfig.get_paths()["stdlib"]) / "dataclasses.py"
    assert is_ambient(_frame_with(str(stdlib)))


def test_a_frozen_caller_is_ambient() -> None:
    assert is_ambient(_frame_with("<frozen importlib._bootstrap>"))


def test_a_string_caller_is_not_ambient() -> None:
    """`python-sb script.py` and `python-sb -c` both stamp the user's code
    `<string>`, so exempting every angle-bracket name exempts the application
    itself -- which the integration suite caught as eval running unguarded."""
    assert not is_ambient(_frame_with("<string>"))


def test_a_site_packages_caller_is_ambient() -> None:
    assert is_ambient(_frame_with("/x/.venv/lib/python3.13/site-packages/typing_inspection/a.py"))


def test_the_guards_own_tag_is_never_ambient() -> None:
    """Evaluated code must not re-enter unguarded."""
    assert not is_ambient(_frame_with("<eval:llm>"))


def test_application_source_is_not_ambient() -> None:
    assert not is_ambient(_frame_with(str(pathlib.Path.cwd() / "samples" / "x" / "tools.py")))


def test_the_sample_tools_are_not_ambient() -> None:
    """Editable installs keep their real path, so the Task 14 sites stay guarded."""
    path = pathlib.Path("samples/langchain-demo/langchain_demo/tools.py").resolve()
    assert not is_ambient(_frame_with(str(path)))


def test_dataclasses_still_works_under_an_armed_declared_profile() -> None:
    """D5: the stdlib generates code with exec; refusing it refuses most programs."""
    import dataclasses

    _deactivate_guard_api()
    activate_api(())
    arm_api()
    _activate(syntax=_syntax("arith"), namespace="closed")
    saved = builtins.exec
    builtins.exec = _patched()["builtins.exec"]  # type: ignore[assignment]
    try:

        @dataclasses.dataclass
        class Point:
            x: int = 0

        assert Point(x=1).x == 1
    finally:
        builtins.exec = saved  # type: ignore[assignment]
        _deactivate_guard_api()
