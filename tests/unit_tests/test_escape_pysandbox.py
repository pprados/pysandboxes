import inspect
import os
import pickle
import sys
from types import ModuleType
from typing import Any, Dict, Set, Tuple

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import RuleApiPermissionError
from pysandboxes.guard_api import activate_guard, patch_rules
from pysandboxes.lifecycle import _reset_for_tests, arm


def test_escape_with_closure() -> None:
    # Find the _original version of io.open (possible if the code is in Python)
    import io

    assert hasattr(io.open, "__closure__"), "Not in a pysandbox"
    original_open = io.open.__closure__[0].cell_contents  # type: ignore[index]
    assert original_open.__module__ in ["_io", "io"], "Not the _original io.open"


@pytest.mark.xfail(
    strict=True,
    reason="escape via __subclasses__: open by construction, out of scope for the wayward-LLM "
    "target (wiki/audit-python-security.md#the-design-target-wayward-llm-generated-code) -- "
    "documented, not scheduled",
)
def test_escape_with_subclasses() -> None:
    # Walking the class hierarchy to reach a guard module and reset its state takes an
    # intent the target reader does not have. Kept strict so that closing it anywhere
    # else breaks here, forcing the audit page to be updated.
    def find_all_subclasses(cls: type) -> Set[type]:
        all_subclasses: Set[type] = set()
        direct_subclasses: Tuple[type, ...] = type.__subclasses__(cls)  # type: ignore[assignment]
        for subclass in direct_subclasses:
            all_subclasses.add(subclass)
            all_subclasses.update(find_all_subclasses(subclass))
        return all_subclasses

    def get_subclasses_modules(subclasses: Set[type]) -> Dict[str, ModuleType]:
        modules: Dict[str, ModuleType] = {}
        for cls in subclasses:
            if inspect.isclass(cls) and hasattr(cls, "__module__"):
                try:
                    module = inspect.getmodule(cls)
                    if module is not None:
                        modules[module.__name__] = module
                except ImportError:
                    # Handle cases where the module might not be importable anymore
                    continue
        return modules

    # Gets the modules associated with these subclasses
    found_modules = get_subclasses_modules(find_all_subclasses(object))
    import_module = found_modules["pysandboxes.guard_import"]
    with pytest.raises(AttributeError):
        import_module._rules = ()  # type: ignore[attr-defined]


@pytest.mark.xfail(
    strict=True,
    reason="sys.meta_path escape: open by construction, out of scope for the wayward-LLM "
    "target (wiki/audit-python-security.md#the-design-target-wayward-llm-generated-code) -- "
    "documented, not scheduled since guard_self was removed",
)
def test_escape_with_meta_path() -> None:
    # Unhooking GuardFinder is a deliberate act, not something code solving the wrong
    # problem does by accident.

    with pytest.raises(AttributeError):
        new_list = list(sys.meta_path)[1:]
        sys.meta_path = new_list


def _install_armed(monkeypatch: pytest.MonkeyPatch, module: ModuleType, name: str) -> None:
    """Replace ``module.name`` with the guard_api wrapper the sandbox installs, then arm."""
    activate_guard(())
    wrapper = patch_rules(learn=False)[f"{module.__name__}.{name}"](getattr(module, name))
    monkeypatch.setattr(module, name, wrapper)
    arm()


def test_a_hostile_pickle_is_refused_once_armed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pickle stream that calls ``os.system`` never runs under an armed sandbox.

    The import guard alone does not stop it: the stream names ``os.system`` through the
    pickle opcodes, and ``os`` is already imported, so no import is ever checked. That is
    not a hole in a real sandbox, because ``pickle.loads`` sits in the ``deserialization``
    category of guard_api, denied by default once armed. The call is refused before a
    single byte of the stream is read, whatever callable it names.
    """
    malicious_pickle = b"cos\nsystem\np0\n(S'echo PICKLE_ALLOWED'\ntRp1\n."
    try:
        _install_armed(monkeypatch, pickle, "loads")
        with pytest.raises(RuleApiPermissionError) as exc:
            pickle.loads(malicious_pickle)
        assert exc.value.category == "deserialization"
    finally:
        _reset_for_tests()


@pytest.mark.xfail(
    strict=True,
    reason="removing pickle from sys.modules does not block the attack: the "
    "_pickle C extension keeps its own module references",
)
def test_escape_with_pickle_blocked() -> None:
    # FAILED PROTECTION ATTEMPT: Removing pickle from sys.modules does NOT block the attack!
    # pickle.loads() uses cached C extension code that doesn't re-import pickle module
    # So even if sys.modules['pickle'] is deleted, pickle.loads() still works!
    # This test documents why naive removal-based blocking FAILS.
    from tests.unit_tests.guard.test_guard_io import (
        _activate_guard_import_blocking_pickle,
        _deactivate_all_rules,
    )

    # Deactivate the default guard from conftest
    _deactivate_all_rules()

    # Attempt to block pickle by removing from sys.modules
    _activate_guard_import_blocking_pickle()

    malicious_pickle = b"cos\nsystem\np0\n(S'echo PICKLE_STILL_WORKS'\ntRp1\n."

    # PROBLEM: Removing pickle from sys.modules is NOT sufficient!
    # The pickle C extension (_pickle) is already loaded and caches module references
    # This is WHY we need guard_import to BLOCK the import at import time, not remove it after.
    # A real guard would make this raise; removal-based blocking does not.
    with pytest.raises((ImportError, pickle.UnpicklingError)):
        pickle.loads(malicious_pickle)  # type: ignore[arg-type]


@pytest.mark.xfail(
    strict=True,
    reason="__globals__ is the dict CPython resolves module-level names through, so it "
    "cannot be taken away: open by construction, out of scope for the wayward-LLM target "
    "(wiki/audit-python-security.md#the-design-target-wayward-llm-generated-code)",
)
def test_escape_with_globals_introspection() -> None:
    # __globals__ trick: any function object exposes its definition module's namespace
    # via __globals__, allowing access to all module-level imports/objects.
    # Attack chain: get a built-in function → inspect its __globals__ → access os
    # Example: a generator's gi_frame exposes function.__globals__
    #
    # Nothing here can be plugged: that dict *is* how CPython resolves every global name
    # and every closure in the process, so it cannot be withheld without breaking the
    # interpreter. The two reads below are precisely the ones that can never raise, which
    # is why each sits inside pytest.raises and the test is xfail rather than passing.

    # Strategy 1: via any method reference
    # object.__init__.__globals__ would expose builtins (if not restricted)
    def harmless_func() -> None:
        pass

    # Even in a sandbox, any function defined in an imported module may have
    # references to restricted modules in its __globals__
    with pytest.raises(AttributeError):
        # Attempt to access __globals__ on a function
        _ = harmless_func.__globals__

    # Strategy 2: via a generator object (if generators allowed)
    def gen_func() -> Any:
        yield 1

    gen = gen_func()
    # gen.gi_frame gives the frame object; f_globals on frame exposes all module globals
    if gen.gi_frame is not None:
        with pytest.raises(AttributeError):
            _ = gen.gi_frame.f_globals


def test_a_name_built_at_run_time_is_refused_at_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Building a sensitive name at run time does not get around guard_api.

    Static filters (RestrictedPython, Basilisk) scan the source for ``os.system`` and are
    beaten by ``"sy" + "stem"``. guard_api does not read the source: it wraps the function
    itself, so the check runs when the function is called, however it was reached --
    ``getattr``, a ``chr()`` chain, bytes decoded at run time.
    """
    name = "sy" + "stem"
    hex_name = bytes.fromhex("73797374656d").decode("ascii")
    try:
        _install_armed(monkeypatch, os, "system")
        for built in (name, hex_name):
            with pytest.raises(RuleApiPermissionError) as exc:
                getattr(os, built)("true")
            assert exc.value.qualname == "os.system"
    finally:
        _reset_for_tests()


# See https://rushter.com/blog/python-code-exec/
# import sys
# sys.modules["builtins"].exec("2+2")
# globals()["__builtins__"].exec("2+2")
# locals()["builtins"].exec("2+2")
# types.FunctionType(compile("print(2+2)","<string>","exec"), globals())()
