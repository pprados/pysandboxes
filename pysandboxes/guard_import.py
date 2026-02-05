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

from .exception import SandBoxError
# %% Generic wrapper
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


class RuleModuleNotFoundError(ModuleNotFoundError, SandBoxError):
    pass


def conv_patch_rules(patch_rules: Dict[str, Callable]) -> PatchRules:
    rules = {}
    # Split path by first module
    for k, v in patch_rules.items():
        module, path = k.split(".", maxsplit=1)
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
    logger.info(f"Apply patch {name=} {module=}")  # FIXME
    all_patch = _patch_rules[name]
    for patch in all_patch:
        cur_module = module
        paths = patch.module_name.split('.')
        for node in paths[:-1]:
            cur_module = cur_module.__dict__[node]
        new_value = patch.patch_factory(cur_module.__dict__[paths[-1]])
        assert not hasattr(cur_module.__dict__[paths[-1]],
                           "__pysandbox__"), "Double injection"
        if __debug__ and isinstance(new_value,
                                    type(_apply_patch)):  # Fake types.FunctionType
            new_value.__pysandbox__ = True  # Add a marker
        cur_module.__dict__[paths[-1]] = new_value


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
                        f"No module named '{module_name}'"
                    )
        # logger.debug(f"exec_module({module.__name__})...")
        self.original_loader.exec_module(module)

        # if not self.done and self.original_spec.name in _rules:
        if self.original_spec.name in _patch_rules:
            _apply_patch(module, self.original_spec.name)

            # logger.error(f"GuardLoader: Injected patch into '{module.__name__}'.")


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
                #     f"GuardFinder: Found original spec via '{type(finder).__name__}'.")
                # Create a new spec using our custom GuardLoader, but with the original spec's data

                # logger.debug(
                #     f"GuardFinder: Found original spec {original_spec.name} via '{type(finder).__name__}'.")
                if original_spec.name in _patch_rules:

                    # logger.debug(f"Inject loader for '{original_spec.name}'")
                    if original_spec.parent:
                        # Use __init__
                        if original_spec.submodule_search_locations:
                            init_file = os.path.join(
                                original_spec.submodule_search_locations[0], "__init__.py")
                        else:
                            init_file = original_spec.origin
                        assert os.path.isfile(init_file), "module without __init__.py"
                        logger.debug(f"Inject loader for '{original_spec.name}'")
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
        return True
    else:
        logger.info("Guard_import was already activated.")
        return False


def _remove_modules() -> None:
    to_remove = set()
    specials = {
        'builtins',
        'sys',
        'importlib',
        'concurrent',
        'asyncio',
        'warnings',
        'logging',
        __name__.rsplit('.', maxsplit=1)[0],
    }
    import sys
    for k, m in dict(sys.modules).items():
        # Detect system modules
        if k in sys.builtin_module_names:  # Il y a builtins
            continue
        flag = False
        for special in specials:
            if k.startswith(special):
                flag = True
                break
        if flag:
            continue

        to_remove.add(k)
    # Special case for pytest
    for k in to_remove:
        if (not k.startswith("_pytest") and
                not k.startswith("pytest")
        ):
            if k in sys.modules:
                # try:
                if k in sys.builtin_module_names:
                    m = sys.modules[k]
                    if m:
                        importlib.reload(m)
                else:
                    del sys.modules[k]
    importlib.invalidate_caches()


def activate_guard_import(
        patch_rules: PatchRules,
        rules: ImportRules,
) -> None:
    global _rules
    if _rules:
        logger.debug("Guard_files was already activated.")
    if _activate_patch_import(patch_rules):
        if "builtins" in patch_rules:
            builtins_module = sys.modules["builtins"]
            _apply_patch(builtins_module, "builtins")
    _rules = rules


if "PYTEST_RUN_CONFIG" in os.environ:
    def _deactivate_guard_import():
        import sys
        global _rules
        _rules = ()
        import sys
        # if _guard_finder in sys.meta_path:
        if True: # FIXME
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
