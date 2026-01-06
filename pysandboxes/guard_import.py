from collections.abc import MutableMapping

from types import ModuleType

from typing import Optional

_module_backlist=[
    "importlib",
    "_interpreter",
]
def guard_import_module(name:str,package:Optional[str]=None) -> ModuleType:
    import importlib
    print(f"trace import_module$({name=},{package=})")
    return importlib.import_module(name,package)

def guard_invalidate_caches():
    import importlib
    print("trace invalidate_caches()")
    # return importlib.invalidate_caches()
    pass  # Not invalidate cache

# %% TODO: pas protégé pour le moment.
import sys
class Guard_sys_module:
    def __init__(self):
        print(f"__init__ avec {type(sys.modules)}")
        self.sys_modules = sys.modules  # FIXME: cache la variable

    def __getitem__(self, key):
        print(f"trace __getitem__ {key=}")
        return self.sys_modules.__getitem__(key)

    def __setitem__(self, key, value):
        print(f"trace __setitem__ {key=} {value=}")
        if key not in _module_backlist:
            self.sys_modules.__setitem__(key, value)
        else:
            print("backlist")

    def __delitem__(self, key):
        print(f"trace __delitem__ {key=}")
        if key not in _module_backlist:
            self.sys_modules.__delitme__(key)
        else:
            print("backlist")

    def __iter__(self):
        self.sys_modules.__iter__()

    def __len__(self):
        self.sys_modules.__len__()

    def get(self,key,*args,**kwargs):
        if args:  # Avec pycharm, il y a un truc qui passe ici dans args
            print(type(args))
            print(type(args[0]))
            print(dir(args[0]))
        print(f"trace key {key=}, {args=}, {kwargs=}")
        # return self.sys_modules.get(key,*args,**kwargs)
        return self.sys_modules.get(key,*args)



guard_sys_module = Guard_sys_module()
setattr(sys,"modules",guard_sys_module)

guard_sys_module["sys"]
sys.modules["sys"]

# #%%
# import importlib
#
# importlib.invalidate_caches()
# setattr(importlib,"import_module",guard_import_module)
# setattr(importlib,"invalidate_caches",guard_invalidate_caches)
#
# importlib.import_module("hack","pack")
