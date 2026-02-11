from types import ModuleType
from typing import Dict, Any, Tuple, Callable
from weakref import WeakKeyDictionary

from .e import RuleAttributeError
from .immutable_dict import ImmutableDict


class GuardModule(ModuleType):
    _states: Dict[
        ModuleType, ImmutableDict[str, Any]] = WeakKeyDictionary()

    __slot__ = ()

    def __init__(self,
                 name,
                 *,
                 original: ModuleType = None,
                 guard_attributs: Tuple[str, ...] = None):
        if not original:
            assert name == "empty_module"
            # Special case for sys module, use by pytest to
            # initialize IGNORED_ATTRIBUTES
            super().__init__(name)
            GuardModule._states[self] = ImmutableDict({})
        else:
            assert (original)
            super().__init__(original.__name__)
            GuardModule._states[self] = ImmutableDict(
                {
                    "guard_attributs": guard_attributs,
                })
            self.__dict__.update(original.__dict__)

    def __setattr__(self, name: str, value: object) -> None:
        guard_attributs = GuardModule._states[self].get("guard_attributs", set())
        if name in guard_attributs:
            raise RuleAttributeError(
                f"Cannot set attribute {self.__name__ + "." + name!r}")
        super().__setattr__(name, value)


def _global_patch_in_sys_module(module: ModuleType) -> ModuleType:
    # Not PEP726 is rejeted
    return GuardModule(
        module.__name__,
        original=module,
        guard_attributs=("meta_path",)
    )

def patch_rules() -> Dict[str, Callable]:
    return {
        # "sys": _global_patch_in_sys_module,
    }


def activate_guard() -> None:
    import sys
    sys.meta_path = tuple(sys.meta_path)  # Change to immutable list
    sys.modules["sys"] = _global_patch_in_sys_module(sys.modules["sys"])

