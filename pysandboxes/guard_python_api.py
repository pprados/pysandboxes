import builtins
import os
from types import ModuleType
from typing import List, Tuple, Union
from typing import Optional

from pip._internal.metadata import importlib

from unit_tests import save_default_values, restore_default_values

_valide_features = {
    "importlib",
}

class Imports_Rule:
    def __init__(self,valid_imports:List[str]):
        self.valid_import = valid_imports

class Feature_Rule:
    def __init__(self,valid_imports:List[str]):
        self.valid_import = valid_imports

PythonAPI = Union[Imports_Rule,Feature_Rule]

def parse_rules(arguments: List[str]) -> Tuple[List[PythonAPI], List[str]]:
    python_api_rules=[]
    ignore_rules = []
    features = []
    modules = []
    for line in arguments:
        if line.startswith("--python-api=ALLOW:"):
            value = line[len("--python-api=ALLOW:"):]
            for feature in value.split(","):
                feature=feature.strip()
                if feature in _valide_features:
                    features.append(feature)
                else:
                    ignore_rules.append(line)
                    break
            else:
                python_api_rules.append(Feature_Rule(features))
        elif line.startswith("--python-api-import=ALLOW:"):
            value = line[len("--python-api-import=ALLOW:"):]
            for module in value.split(","):
                module=module.strip()
                modules.append(module)
    if features:
        python_api_rules.append(Feature_Rule(features))
    if modules:
        python_api_rules.append(Imports_Rule(modules))
    return python_api_rules, ignore_rules


_module_backlist = [
    "importlib",
    "_interpreter",
]


def guard_import_module(name: str, package: Optional[str] = None) -> ModuleType:
    import importlib
    print(f"trace import_module$({name=},{package=})")
    return importlib.import_module(name, package)


def guard_invalidate_caches():
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

    def get(self, key, *args, **kwargs):
        if args:  # Avec pycharm, il y a un truc qui passe ici dans args
            print(type(args))
            print(type(args[0]))
            print(dir(args[0]))
        print(f"trace key {key=}, {args=}, {kwargs=}")
        # return self.sys_modules.get(key,*args,**kwargs)
        return self.sys_modules.get(key, *args)


class ImportBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Optional[str],
                  target: Optional[ModuleType] = None):
        blocked_modules = {"os", "socket"}  # Add your blocked modules here
        if fullname in blocked_modules:
            raise ImportError(f"Import of '{fullname}' is blocked by policy.")
        return None  # Allow other finders to try


# #%%
# import importlib
#
# importlib.invalidate_caches()
# setattr(importlib,"import_module",guard_import_module)
# setattr(importlib,"invalidate_caches",guard_invalidate_caches)
#
# importlib.import_module("hack","pack")

if "PYTEST_RUN_CONFIG" in os.environ:
    _key_to_remember = {
        # TODO
    }

    _memory = dict()
    save_default_values(_memory,
                        _key_to_remember,
                        sys.modules[__name__],
                        )


    def _deactivate_guard_python_api():
        restore_default_values(_memory,
                               sys.modules[__name__])
        global _rules
        _rules = []


def activate_guard_python_api(rules: List[str]) -> None:
    """
    Initializes the file access filter with the given rule list.
    Overrides built-in open and os.listdir functions.
    """
    import sys
    if True:
        sys.setrecursionlimit(2000)  # FIXME
    if True:
        guard_sys_module = Guard_sys_module()
        setattr(sys, "modules", guard_sys_module)

    if True:  # Import
        sys.meta_path.insert(0, ImportBlocker())  # Add to the front of the meta path

    original_import = builtins.__import__

    def custom_import(name, globals=None, locals=None, fromlist=(), level=0):
        blocked = {"os", "socket"}
        if name in blocked:
            raise ImportError(f"Import of '{name}' is forbidden.")
        return original_import(name, globals, locals, fromlist, level)

    builtins.__import__ = custom_import

    def disabled_reload(module):
        raise RuntimeError("Module reloading is disabled.")

    def disabled_import_module(name, package=None):
        raise ImportError(f"Dynamic import of {name} is disabled.")

    importlib.reload = disabled_reload
    importlib.import_module = disabled_import_module

    class ProtectedModules(dict):
        def __delitem__(self, key):
            raise RuntimeError(f"Cannot delete module '{key}' from sys.modules")

    sys.modules = ProtectedModules(sys.modules)
