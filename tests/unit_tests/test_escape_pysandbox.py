import inspect
import pickle
import sys
from types import ModuleType
from typing import Any, Dict, Set, Tuple

import pytest  # type: ignore[import-untyped]


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


@pytest.mark.xfail(
    strict=True,
    reason="guard_api is not armed here, and no Python-level guard covers the pickle opcodes "
    "themselves: armed, pickle.loads is denied (test_guard_api.py::test_armed_denies_pickle_loads)",
)
def test_escape_with_pickle_allowed() -> None:
    # This test exercises the import guard alone, with guard_api disarmed, and demonstrates
    # that pickle.loads() bypasses ALL import guards.
    # The payload calls os.system() through the pickle opcodes, so unpickling it
    # must raise instead of running it. Nothing in the import layer stops it, hence the xfail;
    # the denial armed comes from the guard_api "deserialization" category, not from here.
    # Containing hostile in-process bytecode is the OS sandbox's role; see
    # wiki/audit-python-security.md for why a Python-level pickle guard was dropped.
    malicious_pickle = b"cos\nsystem\np0\n(S'echo PICKLE_ALLOWED'\ntRp1\n."

    with pytest.raises((ImportError, pickle.UnpicklingError)):
        pickle.loads(malicious_pickle)  # type: ignore[arg-type]


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


@pytest.mark.xfail(
    strict=True,
    reason="this layer does no static name scanning, so runtime-built names are never seen: "
    "records a defense never claimed rather than an unfixed hole. Out of scope for the "
    "wayward-LLM target, which has no reason to obfuscate",
)
def test_escape_with_obfuscated_strings() -> None:
    # What this pins is comparative, not a pysandboxes defect: it is why this layer is
    # not built on name matching in the first place.
    #
    # The eval sub-language *does* stop these, and for the opposite reason: it decides at
    # run time, not on the source. __sb_getattr__ and the getattr/vars/hasattr shims hand
    # _check_attr the *value* of the name (eval_runtime.py:213, 293, 321), so
    # '__sub' + 'classes__' arrives there as "__subclasses__" and is refused like the
    # dotted form -- see
    # test_eval_security_corpus.py::test_a_name_built_by_concatenation_dies_on_the_namespace.
    # That guard only covers code routed through guarded_eval; arbitrary bytecode in the
    # host interpreter, which is what this file exercises, never passes through it.
    #
    # Obfuscation bypass: AST-based filters (RestrictedPython, Basilisk) scan for
    # obvious patterns like "__import__", "eval", "exec", "__subclasses__".
    # But Python's dynamic nature allows obfuscating these:
    # - String concatenation: '__sub' + 'classes__'
    # - getattr with constructed names: getattr(type, '__subclasses__')
    # - eval/exec with encoding: compile() then execute
    # - chr() chains: chr(95) + chr(95) builds "__"
    #
    # These bypass static analysis because they construct names at runtime.

    # Attack 1: getattr with concatenated string
    # Directly accessing would be: object.__subclasses__
    # But filter blocks it. Workaround: getattr + string ops
    try:
        subclasses_method = getattr(type, "__sub" + "classes" + "__")
        _ = subclasses_method(object)  # type: ignore[assignment]
        # If this succeeds, we've escaped. In sandbox, should raise AttributeError
        pytest.fail("Obfuscated __subclasses__ access succeeded; sandbox compromised")
    except AttributeError:
        # Expected: sandbox blocked the dynamic attribute access
        pass

    # Attack 2: chr() chain to build forbidden names
    # chr(95) = '_', chr(105) = 'i', chr(109) = 'm', chr(112) = 'p', chr(111) = 'o', chr(114) = 'r', chr(116) = 't'
    # '__import__' = chr(95)*2 + 'import'
    try:
        forbidden_name = chr(95) * 2 + "import" + chr(95) * 2
        # Attempt to access via globals/builtins
        import builtins  # type: ignore[no-redef]

        import_func = getattr(builtins, forbidden_name, None)
        if import_func is not None:
            pytest.fail("chr() obfuscated __import__ access succeeded; sandbox compromised")
    except AttributeError:
        # Expected: sandbox blocked getattr on builtins
        pass

    # Attack 3: string encoding/decoding tricks
    # encode to bytes, then decode back to bypass string filters
    try:
        # Some filters scan source for "__import__" string literals
        # But runtime-constructed strings from bytes bypass this
        obfuscated = b"\x5f\x5f\x69\x6d\x70\x6f\x72\x74\x5f\x5f".decode("ascii")
        # obfuscated now = "__import__"
        import builtins  # type: ignore[no-redef]

        import_func = getattr(builtins, obfuscated, None)
        if import_func is not None:
            pytest.fail("Hex-encoded __import__ access succeeded; sandbox compromised")
    except AttributeError:
        # Expected: sandbox blocked the getattr
        pass


# See https://rushter.com/blog/python-code-exec/
# import sys
# sys.modules["builtins"].exec("2+2")
# globals()["__builtins__"].exec("2+2")
# locals()["builtins"].exec("2+2")
# types.FunctionType(compile("print(2+2)","<string>","exec"), globals())()
