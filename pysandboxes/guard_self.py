# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
from types import ModuleType
from typing import Any, Callable, Dict, MutableMapping, Tuple
from weakref import WeakKeyDictionary

from .e import RuleAttributeError
from .immutable_dict import ImmutableDict


class GuardModule(ModuleType):
    _states: MutableMapping[ModuleType, ImmutableDict[str, Any]] = WeakKeyDictionary()

    __slot__ = ()

    def __new__(cls, name: str, *args: Any, **kwargs: Any) -> Any:
        if "_original" in kwargs and "_guard_attributs" in kwargs:
            return super().__new__(cls, *args, **kwargs)
        else:
            if cls == GuardModule:
                # Return, not guarded module
                obj = ModuleType.__new__(ModuleType)
                obj.__init__(name)  # type: ignore[misc]
                return obj
            else:
                obj = super().__new__(cls)
                super(ModuleType, obj).__init__()  # type: ignore[misc]
                obj.name = name
                return obj

    def __init__(
        self,
        name: str,
        *,
        _original: ModuleType | None = None,
        _guard_attributs: Tuple[str, ...] | None = None,
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
            raise RuleAttributeError(f"Cannot set attribute {self.__name__ + '.' + name!r}")
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


def patch_rules(learn: bool) -> Dict[str, Callable]:
    return {}


def activate_guard() -> None:
    pass  # Nothing at this time
