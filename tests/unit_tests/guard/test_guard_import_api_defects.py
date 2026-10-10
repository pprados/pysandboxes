# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Defects of the import guard and of the sensitive-call registry.

Every refusal is asserted on the refusal itself: no payload here reaches a
real program, a refused call stops before the original function runs.
"""

import asyncio
import importlib
import logging
import pickle
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from types import FunctionType, ModuleType
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


def test_a_relative_import_module_is_judged() -> None:
    import json  # noqa: F401 - loaded, so only the wrapper can judge it

    with _import_rules(), user_code():
        _refused_import(lambda: importlib.import_module(".", "json"), "json")
        _refused_import(lambda: importlib.import_module(".decoder", "json"), "json")


def test_a_relative_dunder_import_is_judged() -> None:
    import json.decoder  # noqa: F401

    with _import_rules(), user_code():
        _refused_import(lambda: __import__("", {"__package__": "json"}, None, ["decoder"], 1), "json")
        _refused_import(lambda: __import__("decoder", {"__package__": "json"}, None, [], 1), "json")


def test_a_relative_import_granted_by_a_rule_passes() -> None:
    import json.decoder  # noqa: F401

    with _import_rules("json"), user_code():
        assert importlib.import_module(".decoder", "json").__name__ == "json.decoder"
        assert __import__("", {"__package__": "json"}, None, ["decoder"], 1).__name__ == "json"


def test_a_kept_package_still_imports_its_own_submodules() -> None:
    """asyncio is kept without a rule, and imports some of its submodules lazily (``from .unix_events import``)."""
    import asyncio.events

    code = compile("from . import events as found", "<asyncio>", "exec")
    own_code = FunctionType(code, dict(vars(asyncio.events)))
    with _import_rules(), user_code():
        own_code()


def test_a_relative_import_from_the_main_module_is_judged() -> None:
    """``__main__`` is kept without a rule, but it is the user's script, not a library."""
    import json.decoder  # noqa: F401

    code = compile('__import__("", {"__package__": "json"}, None, ["decoder"], 1)', "<script>", "exec")
    script_code = FunctionType(code, vars(sys.modules["__main__"]))
    with _import_rules(), user_code():
        _refused_import(script_code, "json")


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
