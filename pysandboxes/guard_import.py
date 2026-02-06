# Define the custom loader class
import importlib
import importlib.abc
import importlib.util
import logging
import os
import sys
from importlib.abc import MetaPathFinder
from types import ModuleType
from typing import Optional, NamedTuple, Callable, Tuple, Dict, List, cast, Any, Set
from weakref import WeakKeyDictionary

from .exceptions import RuleModuleNotFoundError, RuleAttributeError
from .immutable_dict import ImmutableDict
from .learning import is_learning_mode, add_learning_rule
from .main_logger import ErrorMsg
from .types import ConfigLines

logger = logging.getLogger(__name__)


class PatchRule(NamedTuple):
    module_name: str
    patch_factory: Callable


PatchRules = ImmutableDict[str, Tuple[PatchRule, ...]]

ImportRules = Tuple[str, ...]


class LearnImportRule(NamedTuple):
    name: str


def _conv_patch_rules(patch_rules: Dict[str, Callable]) -> PatchRules:
    rules = {}
    # Split path by first module
    for k, v in patch_rules.items():
        if "." in k:
            module, path = k.split(".", maxsplit=1)
        else:
            module, path = k, ""
        patch_list = rules.get(module, [])
        patch_list.append(PatchRule(path, v))
        rules[module] = patch_list

    return PatchRules(rules)


_rules: ImportRules = cast(ImportRules, ())
_patch_rules: PatchRules = cast(PatchRules, ())


def parse_rules(config: ConfigLines,
                errors: List[ErrorMsg],
                ) -> Tuple[ImportRules, ConfigLines]:
    white_list: List[str] = []
    ignore_rules: ConfigLines = []
    for rule in config:
        if rule.rule.startswith("python-import="):
            value = rule.rule.split('=', 1)[1]
            # Accept multiple --python-import rules
            white_list.extend([r.strip() for r in value.split(',')])
        else:
            ignore_rules.append(rule)
    if "*" in white_list:
        white_list = ["*"]
    return tuple(white_list), ignore_rules


def _apply_patch(module, name: str):
    logger.debug(f"Apply patch {name=} {module=}")
    all_patch = _patch_rules[name]
    for patch in all_patch:
        cur_module = module
        if patch.module_name != "":
            paths = patch.module_name.split('.')
            for node in paths[:-1]:
                cur_module = cur_module.__dict__[node]
            if isinstance(cur_module.__dict__[paths[-1]],ModuleType):
                sys.modules[name] = patch.patch_factory(cur_module)
            else:
                new_value = patch.patch_factory(cur_module.__dict__[paths[-1]])
                assert not hasattr(cur_module.__dict__[paths[-1]],
                                   "__pysandbox__"), "Double injection"
                if __debug__ and isinstance(new_value,
                                            type(_apply_patch)):  # Fake types.FunctionType
                    new_value.__pysandbox__ = True  # Add a marker
                cur_module.__dict__[paths[-1]] = new_value
        else:
            # Patch the entire module
            sys.modules[name] = patch.patch_factory(cur_module)


class GuardLoader(importlib.abc.Loader):
    """
    A custom loader that wraps an original loader to modify a module after it
    has been created and executed.
    """
    __slots__ = ("original_spec", "original_loader")

    def __init__(self, original_spec: importlib.util.spec_from_file_location):
        # Store the original spec and loader
        self.original_spec: importlib.util.spec_from_file_location = original_spec
        self.original_loader: importlib.abc.Loader = original_spec.loader

    def create_module(self, spec: importlib.util.spec_from_file_location) -> ModuleType:
        """
        Delegates the module creation to the original loader.
        This gets the base module object from the standard import process.
        """
        logger.debug(f"create_module({spec=}")
        module = self.original_loader.create_module(self.original_spec)
        return module  # Not initialized

    def exec_module(self, module: ModuleType) -> None:
        """
        Executes the module code using the original loader, then performs
        custom modifications.
        This is where we add our custom logic after the standard loading.
        """

        if not module:
            return
        if is_learning_mode():
            add_learning_rule(LearnImportRule(module.__name__))
        else:
            if _rules and _rules[0] != "*":
                module_name = module.__name__
                if module_name not in _rules:
                    raise RuleModuleNotFoundError(
                        f"No module named {module_name!r}"
                    )
        # logger.debug(f"exec_module({module.__name__})...")
        self.original_loader.exec_module(module)

        # if not self.done and self.original_spec.name in _rules:
        if self.original_spec.name in _patch_rules:
            _apply_patch(module, self.original_spec.name)

            # logger.error(f"GuardLoader: Injected patch into {module.__name__!r}.")


# Define the custom finder class
class GuardFinder(importlib.abc.MetaPathFinder):
    __slots__ = ("_finders")

    def __init__(self, finders: MetaPathFinder):
        self._finders = finders

    """
    A custom finder that locates our special module.
    """

    def find_spec(self,
                  fullname: str,
                  path: list[str],
                  target: ModuleType = None
                  ) -> Optional[importlib.util.spec_from_file_location]:
        """
        Finds the specification for a module.
        """
        # logger.debug(f"find_spec({fullname=},{path=},{target=})")

        # Delegate to the rest of the chain to find the original module spec
        # We skip our own finder by checking sys.meta_path from the next index
        # import builtins;builtins.print(f"finder {fullname}")
        for finder in sys.meta_path:
            if finder == self:
                continue
            original_spec: importlib.util.spec_from_file_location = finder.find_spec(
                fullname, path, target)
            if original_spec:
                # logger.debug(
                #     f"GuardFinder: Found original spec via {type(finder).__name__!r}.")
                # Create a new spec using our custom GuardLoader, but with the original spec's data

                # logger.debug(
                #     f"GuardFinder: Found original spec {original_spec.name} via {type(finder).__name__!r}.")
                if original_spec.name in _patch_rules:

                    # logger.debug(f"Inject loader for {original_spec.name!r}")
                    if original_spec.parent:
                        # Use __init__
                        if original_spec.submodule_search_locations:
                            init_file = os.path.join(
                                original_spec.submodule_search_locations[0],
                                "__init__.py")
                        else:
                            init_file = original_spec.origin
                        assert os.path.isfile(init_file), "module without __init__.py"
                        logger.debug(f"Inject loader for {original_spec.name!r}")
                        new_spec = importlib.util.spec_from_file_location(
                            fullname,
                            init_file,
                            loader=GuardLoader(original_spec),
                            submodule_search_locations=
                            original_spec.submodule_search_locations,
                        )
                    else:
                        new_spec = importlib.machinery.ModuleSpec(
                            name=original_spec.name,
                            loader=GuardLoader(original_spec),
                            origin=original_spec.origin,
                            loader_state=original_spec.loader_state,
                        )
                else:
                    new_spec = original_spec
                return new_spec

        # For all other imports, return None to let the standard import
        # mechanism handle them
        return None


_guard_finder: importlib.abc.MetaPathFinder = GuardFinder(sys.meta_path)


def _activate_patch_import(
        patch_rules: PatchRules,
) -> bool:
    import sys
    if _guard_finder not in sys.meta_path:
        global _patch_rules
        _patch_rules = patch_rules

        _remove_modules()
        sys.meta_path.insert(0, _guard_finder)
        sys.meta_path = tuple(sys.meta_path)  # Change to immutable list
        return True
    else:
        logger.info("Guard_import was already activated.")
        return False


# Modules to not remove from sys.modules, and to wait the lazy patch
_not_refresh_modules: Set[str] = (
        {
            'importlib',
            'concurrent',
            'asyncio',
            'warnings',
            'logging',
            '_pytest',
            'pytest',
            __name__.rsplit('.', maxsplit=1)[0],
        } | set(sys.builtin_module_names)
)


def _remove_modules() -> None:
    import sys
    to_remove = set()
    for k, m in dict(sys.modules).items():
        # Detect system modules
        if k in sys.builtin_module_names:  # Il y a builtins
            continue
        for special in _not_refresh_modules:
            if k == special or k.startswith(special + "."):
                break
        else:
            to_remove.add(k)

    importlib.invalidate_caches()
    for k in to_remove:
        if k in sys.modules:
            if k in sys.builtin_module_names:
                m = sys.modules[k]
                if m:
                    importlib.reload(m)
                    pass
            else:
                del sys.modules[k]


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
            assert(original)
            super().__init__(original.__name__)
            GuardModule._states[self] = ImmutableDict(
                {
                    "guard_attributs": guard_attributs,
                })
            self.__dict__.update(original.__dict__)

    def __setattr__(self, name: str, value: object) -> None:
        guard_attributs = GuardModule._states[self].get("guard_attributs",set())
        if name in guard_attributs:
            raise RuleAttributeError(
                f"Cannot set attribute {self.__name__ + "." + name!r}")
        super().__setattr__(name, value)


def _global_patch_in_sys_module(module: ModuleType) -> ModuleType:
    return GuardModule(
        module.__name__,  # FIXME
        original=module,
        guard_attributs=("meta_path",)
                       )


def patch_rules() -> Dict[str, Callable]:
    return {
        # "sys": _global_patch_in_sys_module,  # FIXME: bug in stdout tests
    }


def activate_guard_import(
        patch_rules: Dict[str, Callable],
        rules: ImportRules,
) -> None:
    global _rules
    patch_rules = _conv_patch_rules(patch_rules)
    if _rules:
        logger.debug("Guard_files was already activated.")
    if _activate_patch_import(patch_rules):
        for module in _not_refresh_modules:
            if module in patch_rules:
                builtins_module = sys.modules[module]
                _apply_patch(builtins_module, module)
    _rules = rules


if "PYTEST_RUN_CONFIG" in os.environ:
    def _deactivate_guard_import():
        import sys
        global _rules
        _rules = ()
        import sys
        # if _guard_finder in sys.meta_path:
        if True:  # FIXME
            #     logger.debug("Remove in meta-path")
            #     sys.meta_path.remove(_guard_finder)
            _remove_modules()


def generate_rules(
        learn: Set[Any],
) -> List[str]:
    # Select only parent
    result = set()
    for learn_rule in filter(lambda x: isinstance(x, LearnImportRule), learn):
        result.add(f"python-import={learn_rule.name}")
    return list(result)
