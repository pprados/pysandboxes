# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Defects of the import guard and of the sensitive-call registry.

Every refusal is asserted on the refusal itself: no payload here reaches a
real program, a refused call stops before the original function runs.
"""

import asyncio
import importlib
import importlib.machinery
import logging
import pickle
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Iterator, cast

import pytest

from pysandboxes import guard_api, guard_import
from pysandboxes.e import RuleApiPermissionError, RuleModuleNotFoundError, sandbox_denials
from pysandboxes.guard_api import SENSITIVE_API, _not_applicable, activate_guard, patch_rules
from pysandboxes.guard_import import PatchRule, _conv_patch_rules, framework_imports, user_code
from pysandboxes.lifecycle import arm
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine


@pytest.fixture
def armed() -> Iterator[None]:
    """Arm the call guard with no grant, and return the framework to its pre-install state afterwards."""
    from pysandboxes.lifecycle import _reset_for_tests

    activate_guard(())
    try:
        arm()
        yield
    finally:
        _reset_for_tests()


@contextmanager
def _import_rules(*names: str) -> Iterator[None]:
    """Set the import rules for the block only: a failure must be reported under pytest's own rules."""
    saved = guard_import._rules
    guard_import._rules = names
    try:
        yield
    finally:
        guard_import._rules = saved


def _refused_call(call: Callable[..., object]) -> RuleApiPermissionError:
    with pytest.raises(RuleApiPermissionError) as exc:
        call()
    assert sandbox_denials(exc.value), "the refusal must be recorded as a sandbox denial"
    return exc.value


def _refused_import(call: Callable[[], Any], module: str) -> None:
    with pytest.raises(RuleModuleNotFoundError, match=repr(module)) as exc:
        call()
    assert sandbox_denials(exc.value), "the refusal must be recorded as a sandbox denial"


# 1. Registry gaps.

_NEW_ENTRIES = [
    ("os.setresuid", "privileges"),
    ("posix.setresuid", "privileges"),
    ("os.setresgid", "privileges"),
    ("posix.setresgid", "privileges"),
    ("os.initgroups", "privileges"),
    ("posix.initgroups", "privileges"),
    ("os.unshare", "privileges"),
    ("posix.unshare", "privileges"),
    ("os.setns", "privileges"),
    ("posix.setns", "privileges"),
    ("threading.settrace_all_threads", "introspection"),
    ("threading.setprofile_all_threads", "introspection"),
    ("sys._settraceallthreads", "introspection"),
    ("sys._setprofileallthreads", "introspection"),
    ("sys.monitoring.use_tool_id", "introspection"),
    ("sys.monitoring.register_callback", "introspection"),
    ("ctypes.wstring_at", "native"),
    ("sys.remote_exec", "process-control"),
    ("pickle._loads", "deserialization"),
    ("pickle._load", "deserialization"),
    ("pickle._Unpickler", "deserialization"),
    ("multiprocessing.process.BaseProcess.start", "process-exec"),
]


@pytest.mark.parametrize(("qualname", "category"), _NEW_ENTRIES)
def test_a_sensitive_function_is_registered_and_refused(armed: None, qualname: str, category: str) -> None:
    assert qualname in SENSITIVE_API[category]
    if qualname in _not_applicable():
        pytest.skip(f"{qualname} does not exist on this interpreter")
    table = patch_rules(learn=False)
    wrapped = table[guard_api._PATCH_TARGET.get(qualname, qualname)](lambda *args, **kwargs: "called")
    refusal = _refused_call(wrapped)
    assert (refusal.qualname, refusal.category) == (qualname, category)


def test_a_process_of_a_multiprocessing_context_is_refused(monkeypatch: pytest.MonkeyPatch, armed: None) -> None:
    """``get_context("fork").Process`` derives from BaseProcess, not from ``multiprocessing.Process``."""
    import multiprocessing
    from multiprocessing.process import BaseProcess

    wrapped = patch_rules(learn=False)["multiprocessing.process.BaseProcess.start"](BaseProcess.start)
    monkeypatch.setattr(BaseProcess, "start", wrapped)
    process = multiprocessing.get_context("spawn").Process(target=int)
    assert _refused_call(process.start).qualname == "multiprocessing.process.BaseProcess.start"


def test_the_pure_python_unpickler_is_refused(monkeypatch: pytest.MonkeyPatch, armed: None) -> None:
    """``pickle._loads`` and ``pickle._Unpickler`` run the same opcodes as ``pickle.loads``."""
    wrapped = patch_rules(learn=False)["pickle._Unpickler.__init__"](pickle._Unpickler.__init__)
    monkeypatch.setattr(pickle._Unpickler, "__init__", wrapped)
    benign = pickle.dumps({"harmless": 1})
    assert _refused_call(lambda: pickle._Unpickler(__import__("io").BytesIO(benign))).qualname == "pickle._Unpickler"
    assert isinstance(pickle._Unpickler, type), "the class must stay a class: restricted unpicklers subclass it"


# 2. subprocess binds its own name for fork_exec when it is first imported.


@pytest.mark.skipif(not hasattr(subprocess, "_fork_exec"), reason="subprocess calls _posixsubprocess directly here")
def test_the_subprocess_alias_of_fork_exec_is_wrapped(monkeypatch: pytest.MonkeyPatch, armed: None) -> None:
    subprocess_rules = cast(tuple[PatchRule, ...], _conv_patch_rules(patch_rules(learn=False))["subprocess"])
    rules = [rule for rule in subprocess_rules if rule.code_path == "_fork_exec"]
    assert rules, "subprocess._fork_exec is not in the patch table"
    fork_exec = cast(Callable[..., object], getattr(subprocess, "_fork_exec"))  # noqa: B009
    monkeypatch.setattr(subprocess, "_fork_exec", fork_exec)  # restored by monkeypatch
    monkeypatch.setattr(guard_import, "_patch_rules", {"subprocess": tuple(rules)})
    guard_import._apply_patch(subprocess, "subprocess")

    wrapped_fork_exec = cast(Callable[..., object], getattr(subprocess, "_fork_exec"))  # noqa: B009
    assert getattr(wrapped_fork_exec, "__pysandbox_api__", False), "subprocess._fork_exec is not the wrapper"
    refusal = _refused_call(wrapped_fork_exec)
    assert (refusal.qualname, refusal.category) == ("_posixsubprocess.fork_exec", "process-exec")


# 3. Relative imports.


def test_a_relative_import_granted_by_a_rule_passes() -> None:
    import json.decoder  # noqa: F401

    with _import_rules("json"), user_code():
        assert importlib.import_module(".decoder", "json").__name__ == "json.decoder"
        assert __import__("", {"__package__": "json"}, None, ["decoder"], 1).__name__ == "json"


# 4. Submodules of the modules kept without a rule.


def test_a_submodule_of_a_kept_module_is_judged() -> None:
    import asyncio.subprocess  # noqa: F401 - loaded, so the finder never sees it

    with _import_rules(), user_code():
        assert importlib.import_module("asyncio") is asyncio
        _refused_import(lambda: importlib.import_module("asyncio.subprocess"), "asyncio")
        _refused_import(lambda: __import__("asyncio.subprocess"), "asyncio")


# 5. The framework window belongs to the code that opened it.


def _import_fresh(name: str) -> ModuleType:
    sys.modules.pop(name, None)
    guard_import._pending_modules.pop(name, None)
    return importlib.import_module(name)


def test_the_framework_window_does_not_open_imports_of_another_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_import, "_framework_names", set())
    outcome: list[BaseException | ModuleType] = []
    opened, finished = threading.Event(), threading.Event()

    def other_thread() -> None:
        opened.wait(5)
        try:
            outcome.append(_import_fresh("colorsys"))
        except BaseException as e:
            outcome.append(e)
        finished.set()

    with _import_rules():
        thread = threading.Thread(target=other_thread)
        thread.start()
        with framework_imports():
            opened.set()
            finished.wait(5)
        thread.join(5)

    assert isinstance(outcome[0], RuleModuleNotFoundError), outcome
    assert sandbox_denials(outcome[0])
    assert "colorsys" not in guard_import._framework_names


def test_the_framework_window_still_records_its_own_imports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_import, "_framework_names", set())
    with _import_rules(), framework_imports():
        _import_fresh("colorsys")
    assert "colorsys" in guard_import._framework_names


def test_a_task_created_in_the_window_loses_it_when_the_window_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A task copies the context it is created in: the window must not live on in it."""
    monkeypatch.setattr(guard_import, "_framework_names", set())

    async def scenario() -> None:
        go = asyncio.Event()

        async def later() -> ModuleType:
            await go.wait()
            with _import_rules():
                return _import_fresh("colorsys")

        with framework_imports():
            task = asyncio.get_running_loop().create_task(later())
        go.set()
        with pytest.raises(RuleModuleNotFoundError):
            await task

    asyncio.run(scenario())
    assert "colorsys" not in guard_import._framework_names


# 6. ``python -O`` removes the asserts and every block under ``if __debug__``.


def _guard_import_compiled_with_optimize() -> dict[str, Any]:
    source = Path(guard_import.__file__).read_text()
    namespace: dict[str, Any] = {
        "__name__": "pysandboxes._guard_import_optimized",
        "__package__": "pysandboxes",
        "__file__": guard_import.__file__,
    }
    exec(compile(source, guard_import.__file__, "exec", optimize=1), namespace)
    return namespace


def test_under_optimize_a_second_activation_does_not_wrap_twice() -> None:
    namespace = _guard_import_compiled_with_optimize()
    module = ModuleType("fake")
    module.call = lambda: "original"  # type: ignore[attr-defined]

    def wrap(original: Callable[[], str]) -> Callable[[], str]:
        def wrapper() -> str:
            return f"guarded({original()})"

        return wrapper

    namespace["_patch_rules"] = {"fake": (namespace["PatchRule"]("call", wrap),)}
    namespace["_apply_patch"](module, "fake")
    namespace["_apply_patch"](module, "fake")

    assert module.call() == "guarded(original)"  # type: ignore[attr-defined]


def test_a_later_rule_is_still_applied_after_an_earlier_one_is_already_patched() -> None:
    """The "already patched" guard must ``continue`` to the next rule, not stop the whole loop."""
    module = ModuleType("fake_multi")
    module.one = lambda: "one"  # type: ignore[attr-defined]
    module.two = lambda: "two"  # type: ignore[attr-defined]

    def wrap(original: Callable[[], str]) -> Callable[[], str]:
        def wrapper() -> str:
            return f"guarded({original()})"

        return wrapper

    saved_patch_rules = guard_import._patch_rules
    guard_import._patch_rules = {  # type: ignore[assignment]
        "fake_multi": (PatchRule("one", wrap), PatchRule("two", wrap))
    }
    try:
        guard_import._apply_patch(module, "fake_multi")
        # Undo the second patch only, as if an earlier activation had wrapped it differently.
        module.two = lambda: "two"  # type: ignore[attr-defined]

        guard_import._apply_patch(module, "fake_multi")

        assert module.one() == "guarded(one)"  # type: ignore[attr-defined]
        assert module.two() == "guarded(two)"  # type: ignore[attr-defined]
    finally:
        guard_import._patch_rules = saved_patch_rules


# 7. GuardLoader/GuardFinder pieces that need no real sys.meta_path/sys.modules arming.


def test_exec_module_drops_reinjected_submodules_from_pending() -> None:
    """A submodule reinjected into ``sys.modules`` must also leave ``_pending_modules``.

    Otherwise a later ``find_spec`` on it could still see the stale pending entry.
    """
    package = ModuleType("fakepkg")
    submodule = ModuleType("fakepkg.sub")
    guard_import._pending_modules["fakepkg"] = package
    guard_import._pending_modules["fakepkg.sub"] = submodule
    original_spec = importlib.machinery.ModuleSpec("fakepkg", loader=object())  # type: ignore[arg-type]
    loader = guard_import.GuardLoader("fakepkg", original_spec, package)
    try:
        loader.exec_module(package)
        assert sys.modules.get("fakepkg.sub") is submodule
        assert "fakepkg.sub" not in guard_import._pending_modules
    finally:
        guard_import._pending_modules.pop("fakepkg", None)
        guard_import._pending_modules.pop("fakepkg.sub", None)
        sys.modules.pop("fakepkg.sub", None)


def test_find_spec_reinjects_a_pending_module_under_its_own_spec_name() -> None:
    """A pending module with a real ``__spec__`` must be reinjected under that spec's name."""
    fake = ModuleType("alias")
    fake.__spec__ = importlib.machinery.ModuleSpec("real.name", loader=None)
    guard_import._pending_modules["alias"] = fake
    try:
        with _import_rules("*"):
            spec = guard_import.GuardFinder().find_spec("alias", None, None)
        assert spec is not None
        assert spec.name == "real.name"
    finally:
        guard_import._pending_modules.pop("alias", None)


def test_find_spec_reinjects_a_pending_module_with_no_spec_under_its_module_name() -> None:
    """Without a usable ``__spec__``, the pending module's own ``__name__`` must be used instead."""
    fake = ModuleType("fakename")
    assert fake.__spec__ is None
    guard_import._pending_modules["other_fullname"] = fake
    try:
        with _import_rules("*"):
            spec = guard_import.GuardFinder().find_spec("other_fullname", None, None)
        assert spec is not None
        assert spec.name == "fakename"
    finally:
        guard_import._pending_modules.pop("other_fullname", None)


def test_find_spec_does_not_list_a_pending_non_package_as_having_submodules() -> None:
    """A non-package pending module's ``submodule_search_locations`` must stay unset, not ``list(None)``."""
    fake = ModuleType("fakeleaf")
    fake.__spec__ = importlib.machinery.ModuleSpec("fakeleaf", loader=None)
    assert fake.__spec__.submodule_search_locations is None
    guard_import._pending_modules["fakeleaf"] = fake
    try:
        with _import_rules("*"):
            spec = guard_import.GuardFinder().find_spec("fakeleaf", None, None)
        assert spec is not None
        assert spec.submodule_search_locations is None
    finally:
        guard_import._pending_modules.pop("fakeleaf", None)


def test_find_spec_denies_even_when_running_inside_the_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """``is_learning_mode()`` and ``is_in_sandbox()`` must both hold before a denial is turned into a learned rule."""
    monkeypatch.setattr(guard_import, "is_in_sandbox", lambda: True)
    monkeypatch.setattr(guard_import, "is_learning_mode", lambda: False)
    with _import_rules("os"):
        with pytest.raises(RuleModuleNotFoundError):
            guard_import.GuardFinder().find_spec("subprocess", None, None)


# 8. Small defects.


def test_the_already_activated_message_names_the_import_guard(caplog: pytest.LogCaptureFixture) -> None:
    assert guard_import._activated, "the autouse fixture arms the import guard"
    with caplog.at_level(logging.DEBUG, logger="pysandboxes.guard_import"):
        guard_import.activate_guard_import({}, ("*",))
    messages = [record.getMessage() for record in caplog.records]
    assert any("Guard_import was already activated" in message for message in messages), messages
    assert not any("Guard_files" in message for message in messages), messages


def test_a_dotted_import_rule_is_reported(caplog: pytest.LogCaptureFixture) -> None:
    """Rules name top-level modules: ``os.path`` would never match anything."""
    errors: list[ErrorMsg] = []
    with caplog.at_level(logging.WARNING, logger="pysandboxes.guard_import"):
        guard_import.parse_rules([ConfigLine("python-import=json, os.path", Path("p"), 3)], errors)
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert any("'os.path'" in message and "'os'" in message for message in warnings), warnings
    assert not any("'json'" in message for message in warnings), warnings


def test_only_real_modules_are_kept() -> None:
    assert "threadpool" not in guard_import._KEPT_MODULES
