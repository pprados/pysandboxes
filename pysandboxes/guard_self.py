from types import ModuleType
from typing import Dict, Any, Tuple, Callable
from weakref import WeakKeyDictionary

from .appendonly_dict import AppendOnlyDict
from .e import RuleAttributeError
from .immutable_dict import ImmutableDict


# TODO: limit recursion
# TODO: limit memory

class GuardModule(ModuleType):
    _states: Dict[
        ModuleType, ImmutableDict[str, Any]] = WeakKeyDictionary()

    __slot__ = ()

    def __new__(cls, name: str, *args, **kwargs):
        if "original" in kwargs and "guard_attributs" in kwargs:
            return super().__new__(GuardModule)
        else:
            # Return, not guarded module
            obj = super().__new__(ModuleType)
            obj.__init__(name)
            return obj

    def __init__(self,
                 name,
                 *,
                 original: ModuleType,
                 guard_attributs: Tuple[str, ...]):
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
    # Note: PEP726 is rejeted
    import sys
    # sys.modules = AppendOnlyDict(
    #     module.modules,
    #     onetime_set={"sys"})
    # guard_module = GuardModule(
    #     module.__name__,
    #     original=module,
    #     guard_attributs=("meta_path", "modules")
    # )
    # return guard_module
    return module

def patch_rules() -> Dict[str, Callable]:
    return {
        # "sys": _global_patch_in_sys_module,
    }


def activate_guard() -> None:
    import sys
    sys.meta_path = tuple(sys.meta_path)  # Change to immutable list
    sys.modules["sys"] = _global_patch_in_sys_module(sys.modules["sys"])
