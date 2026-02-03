# Define the custom loader class
import importlib
import importlib.abc
import importlib.util
import logging
import sys
from importlib.abc import MetaPathFinder
from types import ModuleType
from typing import Optional, NamedTuple, Callable, Tuple, Dict, List, cast, Any, Set

from .exception import SandBoxError
from .guard_module import readonly_module
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
    #  TODO: faire les sous modules comme os.path
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
        if rule.rule.startswith("--python-import="):
            value = rule.rule.split('=', 1)[1]
            # Accept multiple --python-import rules
            white_list.extend([r.strip() for r in value.split(',')])
        else:
            ignore_rules.append(rule)
    return tuple(white_list), ignore_rules


class GuardLoader(importlib.abc.Loader):
    """
    A custom loader that wraps an original loader to modify a module after it
    has been created and executed.
    """

    def __init__(self, original_spec: importlib.util.spec_from_file_location):
        # Store the original spec and loader
        self.original_spec: importlib.util.spec_from_file_location = original_spec
        self.original_loader: importlib.abc.Loader = original_spec.loader
        self.done = False

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
            if module.__name__ not in _rules:
                raise RuleModuleNotFoundError(
                    f"No module named '{module.__name__}'"
                )
        logger.debug(f"exec_module({module.__name__})")
        self.original_loader.exec_module(module)

        # if not self.done and self.original_spec.name in _rules:
        # logger.debug(f"{self.original_spec.name=}")
        if self.original_spec.name in _patch_rules:
            all_patch = _patch_rules[self.original_spec.name]
            for patch in all_patch:
                cur_module = module
                path = ""
                paths = patch.module_name.split('.')
                for node in paths[:-1]:
                    logger.debug(f"{path=} {cur_module=}")
                    cur_module = cur_module.__dict__[node]
                new_value = patch.patch_factory(cur_module.__dict__[paths[-1]])
                cur_module.__dict__[paths[-1]] = new_value
                self.done = True  # FIXME

            # logger.debug(f"GuardLoader: Injected patch into '{module.__name__}'.")

        # TODO: pour les modules pysandbox ?
        # # Override the __setattr__ method of the module to prevent changes
        # def immutable_setattr(obj: ModuleType, name: str, value: Any) -> None:
        #     raise AttributeError(
        #         f"Cannot reassign attributes on immutable module '{obj.__name__}'")
        #
        # # Assign the new method to the module's __setattr__
        # module.__setattr__ = immutable_setattr


# Define the custom finder class
class GuardFinder(importlib.abc.MetaPathFinder):
    def __init__(self, finders: MetaPathFinder):
        self._finders = finders

    # TODO: This method is used by importlib.invalidate_caches().
    def invalidate_caches(self):
        pass

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
        # if fullname and fullname.startswith("pysandboxes"):  # FIXME: util ?
        #     return None
        # Intercept ONLY the 'os.path' import
        if True:  # fullname == "os.path":
            # print(f"GuardFinder: Intercepting import for '{fullname}'.")

            # Delegate to the rest of the chain to find the original module spec
            # We skip our own finder by checking sys.meta_path from the next index
            for finder in sys.meta_path:
                if finder == self:
                    continue
                original_spec: importlib.util.spec_from_file_location = finder.find_spec(
                    fullname, path, target)
                if original_spec:
                    # logger.debug(
                    #     f"GuardFinder: Found original spec via '{type(finder).__name__}'.")
                    # Create a new spec using our custom GuardLoader, but with the original spec's data
                    # def __init__(self, name, loader, *, origin=None, loader_state=None,
                    #              is_package=None):

                    logger.debug(
                        f"GuardFinder: Found original spec {original_spec.name} via '{type(finder).__name__}'.")
                    if original_spec.name in _patch_rules:

                        logger.info(f"Inject patcher for {original_spec.name}")
                        new_spec = importlib.machinery.ModuleSpec(
                            name=original_spec.name,
                            loader=GuardLoader(original_spec),
                            origin=original_spec.origin,
                            # is_package=original_spec.is_package,
                            loader_state=original_spec.loader_state,
                            # submodule_search_locations=original_spec.submodule_search_locations,
                        )
                    else:
                        new_spec = original_spec
                    return new_spec
                    # return importlib.util.spec_from_loader(
                    #     fullname,
                    #     GuardLoader(original_spec),
                    #     origin=original_spec.origin,
                    #     is_package=original_spec.is_package,
                    # )

        # For all other imports, return None to let the standard import mechanism handle them
        return None


def _activate_patch_import(
        patch_rules: PatchRules,
):
    global _patch_rules
    _patch_rules = patch_rules

    to_remove = set()

    specials = {
        'sys',
        'concurrent',
        'asyncio',
        "importlib",
        __name__.rsplit('.', maxsplit=1)[0],
    }
    import sys
    for k, m in dict(sys.modules).items():
        # Detect system modules
        if k in sys.builtin_module_names:
            continue
        flag = False
        for special in specials:
            if k.startswith(special):
                flag = True
                break
        if flag:
            continue

        to_remove.add(k)

    importlib.invalidate_caches()
    for k in to_remove:
        del sys.modules[k]
    import sys
    sys.meta_path.insert(0, GuardFinder(sys.meta_path))
    assert "io" not in sys.modules


def activate_guard_import(
        patch_rules: PatchRules,
        rules: ImportRules,
) -> None:
    global _rules
    if _rules:
        logger.info("Guard_files was already activated.")
    if not _rules:
        _activate_patch_import(patch_rules)
        _rules = rules
    readonly_module(__name__)


def generate_rules(
        learn: Set[Any],
) -> List[str]:
    # Select only parent
    result = set()
    for learn_rule in filter(lambda x: isinstance(x, LearnImportRule), learn):
        result.add(f"--python-import={learn_rule.name}")
    return list(result)
