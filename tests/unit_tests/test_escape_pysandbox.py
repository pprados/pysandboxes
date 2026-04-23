import inspect
import pickle
import sys
from types import ModuleType
from typing import Dict, Set, Tuple

import pytest

from pysandboxes import RuleAttributeError, RuleModuleNotFoundError


def test_escape_with_closure() -> None:
    # Find the _original version of io.open (possible if the code is in Python)
    import io

    assert hasattr(io.open, "__closure__"), "Not in a pysandbox"
    original_open = io.open.__closure__[0].cell_contents  # type: ignore[index]
    assert original_open.__module__ in ["_io", "io"], "Not the _original io.open"


@pytest.mark.skip
def test_escape_with_subclasses() -> None:
    # TODO Try to block the __subclasses__ access
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
    with pytest.raises(RuleAttributeError):
        import_module._rules = ()  # type: ignore[attr-defined]


@pytest.mark.skip
def test_escape_with_meta_path() -> None:
    import sys

    with pytest.raises(RuleAttributeError):
        new_list = list(sys.meta_path)[1:]
        sys.meta_path = new_list


def test_escape_with_pickle_allowed() -> None:
    # VULNERABLE (default): Pickle is ALLOWED by default (_activate_guard_import_for_tests)
    # This test demonstrates pickle.loads() bypasses ALL import guards
    malicious_pickle = b"cos\nsystem\np0\n(S'echo PICKLE_ALLOWED'\ntRp1\n."

    result = pickle.loads(malicious_pickle)  # type: ignore[arg-type]
    # os.system() returns 0 on success
    if result == 0:
        pytest.fail("VULNERABLE: pickle.loads() bypassed guards (allowed by default)")


def test_escape_with_pickle_blocked() -> None:
    # FAILED PROTECTION ATTEMPT: Removing pickle from sys.modules does NOT block the attack!
    # pickle.loads() uses cached C extension code that doesn't re-import pickle module
    # So even if sys.modules['pickle'] is deleted, pickle.loads() still works!
    # This test documents why naive removal-based blocking FAILS.
    from tests.unit_tests.guard.test_guard_io import (
        _deactivate_all_rules,
        _activate_guard_import_blocking_pickle,
    )

    # Deactivate the default guard from conftest
    _deactivate_all_rules()

    # Attempt to block pickle by removing from sys.modules
    _activate_guard_import_blocking_pickle()

    malicious_pickle = b"cos\nsystem\np0\n(S'echo PICKLE_STILL_WORKS'\ntRp1\n."

    # PROBLEM: Removing pickle from sys.modules is NOT sufficient!
    # The pickle C extension (_pickle) is already loaded and caches module references
    # This is WHY we need guard_import to BLOCK the import at import time, not remove it after
    result = pickle.loads(malicious_pickle)  # type: ignore[arg-type]

    # If os.system() executed (result == 0), blocking failed!
    if result == 0:
        pytest.fail(
            "EXPECTED FAILURE: Removing pickle from sys.modules does NOT block attack. "
            "Need real import guard that blocks pickle BEFORE it's loaded."
        )


# See https://rushter.com/blog/python-code-exec/
# import sys
# sys.modules["builtins"].exec("2+2")
# globals()["__builtins__"].exec("2+2")
# locals()["builtins"].exec("2+2")
# types.FunctionType(compile("print(2+2)","<string>","exec"), globals())()
