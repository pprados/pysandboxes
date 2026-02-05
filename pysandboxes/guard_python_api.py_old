import sys
import logging
import os
import sysconfig
from types import ModuleType
from typing import List, Tuple, Union, Literal, Set
from typing import Optional

from pysandboxes.types import ConfigLines

logger = logging.getLogger(__name__)

_valide_features = {
    "importlib",
}

# TODO: faire une injection paresseuse des patchs, lors de l'import des modules
# via un paramétrage globale simple.
# TODO Essayer de capturer le host des connexion réseaux, par capture des résolutions DNS précédante.
# TODO: inspiration https://man7.org/linux/man-pages/man1/firejail.1.html
# To help creating useful seccomp filters more easily, the
#               following system call groups are defined: @aio, @basic-io,
#               @chown, @clock, @cpu-emulation, @debug, @default, @default-
#               nodebuggers, @default-keep, @file-system, @io-event, @ipc,
#               @keyring, @memlock, @module, @mount, @network-io,
#               @obsolete, @privileged, @process, @raw-io, @reboot,
#               @resources, @setuid, @swap, @sync, @system-service and
#               @timer.  More information about groups can be found in
#               /usr/share/doc/firejail/syscalls.txt
# TODO Lors de la désérialisation d'un flux pickle, Python exécute les instructions
#  contenues dans le flux pour reconstruire l'objet. Si un attaquant peut modifier ou
#  injecter un flux pickle malveillant, il peut inclure des instructions qui appellent
#  des fonctions du système d'exploitation (comme os.system ou subprocess.run),
#  exécutent des scripts, ou manipulent des fichiers.

# import os
# import pickle
#
# class Exploit:
#     def __reduce__(self):
#         # This method is called by pickle to "reduce" the object
#         # for serialization. An attacker can craft this to point
#         # to arbitrary functions and arguments.
#         return (os.system, ('echo PWNED! ; cat /etc/passwd',))
#
# # This is the "malicious" object. If an attacker can get you to unpickle this,
# # os.system('echo PWNED! ; cat /etc/passwd') will be executed.
# malicious_pickle = pickle.dumps(Exploit())
#
# # If a vulnerable application does:
# # pickle.loads(malicious_pickle)
# # It will execute the command.

def _is_system_module(module:ModuleType) -> bool:
    # Cas 1: Module intégré (pas de fichier associé)
    if module.__name__ in sys.builtin_module_names:
        return True

    # Cas 2: Vérifier via sys.modules et le chemin du module
    if module and hasattr(module, '__file__') and module.__file__:
        module_path = os.path.abspath(module.__file__)

        # 2a: Vérifier les chemins de la bibliothèque standard
        stdlib_paths = [
            sysconfig.get_path("stdlib"),
            sysconfig.get_path("platstdlib"),
            os.path.join(sysconfig.get_path("data"), "DLLs")  # Pour Windows
        ]

        # 2b: Vérifier les site-packages système
        system_site_packages = [
            sysconfig.get_path("purelib"),
            sysconfig.get_path("platlib")
        ]

        # 2c: Vérifier les chemins de base du système
        all_system_paths = stdlib_paths + system_site_packages
        all_system_paths = [os.path.abspath(p) for p in all_system_paths if p]

        for system_path in all_system_paths:
            if module_path.startswith(system_path):
                return True

    return False

def _loaded_sys_modules() -> List[ModuleType]:
    print(sys.modules.keys())
    dict(sys.modules.items())
    return [module for _,module in dict(sys.modules).items() if not _is_system_module(module)]


class Imports_Rule:
    def __init__(self, valid_imports: Set[str], mode: Literal["allow", "learn"]):
        self.valid_import = valid_imports
        self.learn_import = set()
        self.mode = mode

    def __del__(self):
        if self.mode == "learn":
            with open("learned_imports.txt", "w") as f:  # FIXME
                f.write("--python-api-import=ALLOW:" + ",".join(self.learn_import))


class Feature_Rule:
    def __init__(self, valid_imports: Set[str]):
        self.valid_import = valid_imports


PythonAPIRules = Union[Imports_Rule, Feature_Rule]

_rules: List[PythonAPIRules] = []


def parse_rules(arguments: ConfigLines) -> Tuple[List[PythonAPIRules], ConfigLines]:
    python_api_rules = []
    import_mode: Literal["allow", "learn"] = "allow"
    ignore_rules = []
    features = set()
    modules = set()
    for line in arguments:
        if line.startswith("--python-api=ALLOW:"):
            value = line[len("--python-api=ALLOW:"):]
            for feature in value.split(","):
                feature = feature.strip()
                if feature in _valide_features:
                    features.append(feature)
                else:
                    ignore_rules.append(line)
                    break
            else:
                python_api_rules.append(Feature_Rule(features))
        elif line.startswith("--python-api-import="):
            if line.startswith("--python-api-import=ALLOW:"):
                value = line[len("--python-api-import=ALLOW:"):]
                for module in value.split(","):
                    module = module.strip()
                    if module:  # Remove empty modules
                        modules.add(module)
            elif line == "--python-api-import=LEARN":
                import_mode = "learn"
            else:
                pass  # TODO
    if features:
        python_api_rules.append(Feature_Rule(features))
    if modules or import_mode == "learn":
        python_api_rules.append(Imports_Rule(modules, mode=import_mode))
    return python_api_rules, ignore_rules


_module_backlist = [
    "importlib",
    "_interpreter",
]


def guard_import_module(name: str, package: Optional[str] = None) -> ModuleType:
    # TODO: voir le chat https://gemini.google.com/share/6a3e41fa4fbc
    # pour voir comment faire un patch lazy lors des import
    import importlib
    print(f"trace import_module$({name=},{package=})")
    return importlib.import_module(name, package)


def guard_invalidate_caches():
    print("trace invalidate_caches()")
    # return importlib.invalidate_caches()
    pass  # Not invalidate cache


# %% TODO: pas protégé pour le moment.


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

_import_blocker=None
def _activate_guard_import(rules: List[PythonAPIRules]):
    import_rules = None
    for rule in _rules:
        if isinstance(rule, Imports_Rule):
            import_rules = rule
            break
    if not import_rules:
        raise ValueError("No import rules found")

    class ImportBlocker:
        def find_spec(self, fullname: str, path: Optional[str],
                      target: Optional[ModuleType] = None):
            global _rules
            for import_name in import_rules.valid_import:
                if import_name[-1] == "*":
                    if fullname.startswith(import_name[:-1]) :
                        break
                    if fullname == import_name[:-2] :
                        break
                else:
                    if fullname == import_name:
                        break
            else:
                if import_rules.mode == "learn":
                    import_rules.learn_import.add(fullname)
                    print(f"*** LEARN {fullname=}")
                    return None
                raise RuleImportError(f"Import of '{fullname}' is forbidden.")

            return None  # Allow other finders to try

    # importlib.invalidate_caches()
    loaded_sys_modules = _loaded_sys_modules()
    for key,module in dict(sys.modules).items():
        if module not in loaded_sys_modules:
            sys.modules.pop(key)
        else:
            print(f"garde module {key=}")
    # for name in _loaded_sys_modules():
    #     if (name not in sys.builtin_module_names
    #             # and name[0] != "_"
    #     ):
    #         sys.modules.pop(name)
    #     else:
    #         print(f"garde module {name=}")
    sys.meta_path.insert(0, _import_blocker:=ImportBlocker())  # Add to the front of the meta path


# #%%
# import importlib
#
# importlib.invalidate_caches()
# setattr(importlib,"import_module",guard_import_module)
# setattr(importlib,"invalidate_caches",guard_invalidate_caches)
#
# importlib.import_module("hack","pack")

if "PYTEST_RUN_CONFIG" in os.environ:
    def _deactivate_guard_python_api():
        global _rules,_import_blocker
        _rules = []
        # if sys.meta_path[0]
        # sys.meta_path.remove(_import_blocker)  # Add to the front of the meta path
        sys.meta_path.pop(0)  # FIXME: préférable par instrance
        # FIXME: desactive les modules déjà chargés ?
        # for name in list(sys.modules):
        #     if name not in ('sys', "builtins", 'importlib', "pytest",
        #     #         # and name[0] != "_"
        #     ):
        #         sys.modules.pop(name)
        #     # else:
        #     #     print(f"garde module {name=}")
        print("************ PURGE DONE",flush=True)


def activate_guard_python_api(rules: List[PythonAPIRules]) -> None:
    """
    Initializes the file access filter with the given rule list.
    Overrides built-in open and os.listdir functions.
    """
    if not rules:
        return
    global _rules
    install_wrapper = not _rules
    _rules = rules

    # TODO: voir sys.displayhook
    # TODO:  if async_:
    #                     await eval(code_obj, self.user_global_ns, self.user_ns)
    #                 else:
    #                     exec(code_obj, self.user_global_ns, self.user_ns)
    _activate_guard_import(rules)
    # import sys
    # if True:
    #     sys.setrecursionlimit(2000)  # FIXME
    # if True:
    #     guard_sys_module = Guard_sys_module()
    #     setattr(sys, "modules", guard_sys_module)
    #
    # if True:  # Import
    #     sys.meta_path.insert(0, ImportBlocker())  # Add to the front of the meta path
    #
    # original_import = builtins.__import__
    #
    # def custom_import(name, globals=None, locals=None, fromlist=(), level=0):
    #     blocked = {"os", "socket"}
    #     if name in blocked:
    #         raise ImportError(f"Import of '{name}' is forbidden.")
    #     return original_import(name, globals, locals, fromlist, level)
    #
    # builtins.__import__ = custom_import
    #
    # def disabled_reload(module):
    #     raise RuntimeError("Module reloading is disabled.")
    #
    # def disabled_import_module(name, package=None):
    #     raise ImportError(f"Dynamic import of {name} is disabled.")
    #
    # importlib.reload = disabled_reload
    # importlib.import_module = disabled_import_module

    # class ProtectedModules(dict):
    #     def __delitem__(self, key):
    #         raise RuntimeError(f"Cannot delete module '{key}' from sys.modules")
    #
    # sys.modules = ProtectedModules(sys.modules)
