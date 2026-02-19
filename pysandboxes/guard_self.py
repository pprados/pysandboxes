from types import ModuleType
from typing import Any, Callable, Dict, Tuple
from weakref import WeakKeyDictionary

from .e import RuleAttributeError
from .immutable_dict import ImmutableDict

# TODO: limit recursion
# TODO: limit memory


class GuardModule(ModuleType):
    _states: Dict[ModuleType, ImmutableDict[str, Any]] = WeakKeyDictionary()

    __slot__ = ()

    def __new__(cls, name: str, *args, **kwargs):
        if "_original" in kwargs and "_guard_attributs" in kwargs:
            return super().__new__(GuardModule, *args, **kwargs)
        else:
            if cls == GuardModule:
                # Return, not guarded module
                obj = super().__new__(ModuleType)
                obj.__init__(name)
                return obj
            else:
                obj = super().__new__(cls)
                super(ModuleType, obj).__init__(name)
                return obj

    def __init__(
        self,
        name,
        *,
        _original: ModuleType = None,
        _guard_attributs: Tuple[str, ...] = None,
    ):
        super().__init__(name)
        if _original:
            GuardModule._states[self] = ImmutableDict(
                {
                    "_guard_attributs": _guard_attributs,
                }
            )
            self.__dict__.update(_original.__dict__)

    def __setattr__(self, name: str, value: object) -> None:
        guard_attributs = GuardModule._states[self].get("_guard_attributs", set())
        if name in guard_attributs:
            raise RuleAttributeError(
                f"Cannot set attribute {self.__name__ + '.' + name!r}"
            )
        super().__setattr__(name, value)


def _global_patch_in_sys_module(module: ModuleType) -> ModuleType:
    # Note: PEP726 is rejeted
    # sys.modules = AppendOnlyDict(
    #     module.modules,
    #     onetime_set={"sys"})
    # TODO GuardModule not working
    # guard_module = GuardModule(
    #     module.__name__,
    #     _original=module,
    #     _guard_attributs=("meta_path", "modules")
    # )
    # return guard_module
    return module


def patch_rules() -> Dict[str, Callable]:
    return {}


def activate_guard() -> None:
    import sys

    sys.meta_path = tuple(sys.meta_path)  # Change to immutable list
    sys.modules["sys"] = _global_patch_in_sys_module(sys.modules["sys"])
