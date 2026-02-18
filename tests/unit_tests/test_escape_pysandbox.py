import inspect
from types import ModuleType
from typing import Set, Tuple, Dict

import pytest

from pysandboxes import RuleAttributeError
from unit_tests.guard.test_guard_io import _reset_rules



def test_escape_with_closure():
    # Find the _original version of io.open (possible if the code is in Python)
    import io
    assert hasattr(io.open, "__closure__"), "Not in a pysandbox"
    original_open = io.open.__closure__[0].cell_contents
    assert original_open.__module__ == "_io", "Not the _original io.open"


@pytest.mark.skip
def test_escape_with_subclasses():
    # TODO Try to block the __subclasses__ access
    def find_all_subclasses(cls: type) -> Set[type]:
        all_subclasses: Set[type] = set()
        direct_subclasses: Tuple[type, ...] = type.__subclasses__(cls)
        for subclass in direct_subclasses:
            all_subclasses.add(subclass)
            all_subclasses.update(find_all_subclasses(subclass))
        return all_subclasses

    def get_subclasses_modules(subclasses: Set[type]) -> Dict[str,ModuleType]:
        modules: Dict[str,ModuleType] = {}
        for cls in subclasses:
            if inspect.isclass(cls) and hasattr(cls, '__module__'):
                try:
                    module = inspect.getmodule(cls)
                    if module is not None:
                        modules[module.__name__]=module
                except ImportError:
                    # Handle cases where the module might not be importable anymore
                    continue
        return modules

    # Gets the modules associated with these subclasses
    found_modules = get_subclasses_modules(find_all_subclasses(object))
    import_module = found_modules["pysandboxes.guard_import"]
    with pytest.raises(RuleAttributeError):
        import_module._rules = ()  # Remove rules


@pytest.mark.skip
def test_escape_with_meta_path():
    import sys
    with pytest.raises(RuleAttributeError):
        new_list = list(sys.meta_path)[1:]
        sys.meta_path = new_list
