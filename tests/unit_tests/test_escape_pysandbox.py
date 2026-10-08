import importlib.abc
import importlib.machinery
import importlib.util
import inspect
import os
import pickle
import sys
from types import ModuleType
from typing import Any, Dict, Set, Tuple

import pytest  # type: ignore[import-untyped]

from pysandboxes import guard_import
from pysandboxes.e import RuleApiPermissionError, RuleModuleNotFoundError
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
@pytest.mark.filterwarnings("ignore:'_UnionGenericAlias' is deprecated:DeprecationWarning")
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


class _AliasFinder:
    """A framework-style finder (crewai, wrapt, httpx2) that serves one module of its own."""

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        if fullname != "framework_alias":
            return None
        return importlib.util.spec_from_loader(fullname, _AliasLoader())


class _AliasLoader(importlib.abc.Loader):
    def create_module(self, spec: Any) -> None:
        return None

    def exec_module(self, module: ModuleType) -> None:
        module.VALUE = 42  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "tamper",
    [
        pytest.param(lambda finders: finders[1:], id="guard-removed"),
        pytest.param(lambda finders: [importlib.machinery.PathFinder, *finders], id="finder-ahead-of-guard"),
    ],
)
def test_tampering_with_meta_path_leaves_the_next_import_guarded(tamper: Any) -> None:
    """``sys.meta_path`` is a plain list, so code can unhook the import guard or get ahead of it.

    An audit hook, which Python cannot remove, puts the guard back at the head before
    each import, so the module the rules do not name is still refused.
    """
    _reset_for_tests()  # the conftest activated the guard with "*"; these rules must take its place
    guard_import.activate_guard_import({}, ("json", "framework_alias"))
    saved = list(sys.meta_path)
    sys.modules.pop("colorsys", None)
    try:
        sys.meta_path = tamper(saved)
        with pytest.raises(RuleModuleNotFoundError, match="'colorsys' is not allowed by a rule"):
            import colorsys  # noqa: F401
        assert sys.meta_path[0] is guard_import._guard_finder
    finally:
        sys.meta_path = saved
        _reset_for_tests()


def test_a_framework_finder_ahead_of_the_guard_keeps_working() -> None:
    """Frameworks insert their finder at the head when imported; their modules still load."""
    _reset_for_tests()  # the conftest activated the guard with "*"; these rules must take its place
    guard_import.activate_guard_import({}, ("json", "framework_alias"))
    saved = list(sys.meta_path)
    sys.modules.pop("framework_alias", None)
    try:
        sys.meta_path.insert(0, _AliasFinder())
        import framework_alias  # type: ignore[import-not-found]

        assert framework_alias.VALUE == 42
        assert sys.meta_path[0] is guard_import._guard_finder
    finally:
        sys.meta_path = saved
        sys.modules.pop("framework_alias", None)
        _reset_for_tests()


def test_a_c_extension_still_loads_under_the_audit_hook() -> None:
    """Loading a ``.so`` raises a second ``import`` event, with None for sys.meta_path.

    It is not a walk of the finders, so it must pass: refusing it stopped the sandbox
    daemon from importing pydantic_core.
    """
    saved = {name: module for name, module in sys.modules.items() if name.startswith("pydantic_core")}
    for name in saved:
        del sys.modules[name]
    guard_import.activate_guard_import({}, ("*",))
    try:
        import pydantic_core._pydantic_core as extension

        origin = extension.__spec__.origin if extension.__spec__ else None
        assert origin is not None and origin.endswith((".so", ".pyd"))
    finally:
        _reset_for_tests()
        sys.modules.update(saved)


def test_a_meta_path_that_is_no_longer_a_list_refuses_the_import() -> None:
    guard_import.activate_guard_import({}, ("*",))
    saved = sys.meta_path
    sys.modules.pop("colorsys", None)
    try:
        sys.meta_path = tuple(saved[1:])  # type: ignore[assignment]
        with pytest.raises(RuleModuleNotFoundError, match="no longer a list"):
            import colorsys  # noqa: F401
    finally:
        sys.meta_path = saved
        _reset_for_tests()


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
