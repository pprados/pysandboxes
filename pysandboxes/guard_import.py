# Define the custom loader class
import importlib
import importlib.abc
import importlib.util
import logging
import os
import sys
from importlib import resources
from importlib.abc import MetaPathFinder
from types import ModuleType
from typing import Optional, NamedTuple, Callable, Tuple, Dict, List, cast, Any, Set, \
    Iterable

from .e import RuleModuleNotFoundError
from .immutable_dict import ImmutableDict
from .learning import is_learning_mode, add_learning_rule
from .main_logger import ErrorMsg
from .sb_types import ConfigLines
from .tools import is_in_sandbox

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


def _apply_patch(module, name: str) -> None:
    logger.debug(f"Apply patch {name=} {module=}")
    all_patch = _patch_rules[name]
    for patch in all_patch:
        parent_object = None
        cur_object = module
        if patch.module_name != "":
            paths = patch.module_name.split('.')
            for node in paths[:-1]:
                parent_object = cur_object
                cur_object = cur_object.__dict__[node]
            new_value = patch.patch_factory(getattr(cur_object, paths[-1]))
            assert not hasattr(new_value,
                               "__pysandbox__"), "Double injection"
            if __debug__ and isinstance(new_value,
                                        type(
                                            _apply_patch)):  # Fake kinds.FunctionType
                new_value.__pysandbox__ = True  # Add a marker
            setattr(cur_object, paths[-1], new_value)
        else:
            # Patch the entire module
            sys.modules[name] = patch.patch_factory(cur_object)

class GuardLoader(importlib.abc.Loader):
    """
    A custom loader that wraps an _original loader to modify a module after it
    has been created and executed.
    """
    __slots__ = ("original_spec", "original_loader")

    def __init__(self, original_spec: importlib.util.spec_from_file_location):
        # Store the _original spec and loader
        self.original_spec: importlib.util.spec_from_file_location = original_spec
        self.original_loader: importlib.abc.Loader = original_spec.loader

    def create_module(self, spec: importlib.util.spec_from_file_location) -> ModuleType:
        """
        Delegates the module creation to the _original loader.
        This gets the base module object from the standard import process.
        """
        # logger.debug(f"create_module({spec=}")
        module = self.original_loader.create_module(self.original_spec)
        return module  # Not initialized

    def exec_module(self, module: ModuleType) -> None:
        """
        Executes the module code using the _original loader, then performs
        custom modifications.
        This is where we add our custom logic after the standard loading.
        """

        if module is None:
            return
        if not is_learning_mode():
            if _rules and _rules[0] != "*":
                module_name = module.__name__
                # Reactiver le filtre de module
                if module_name not in _rules:
                    raise RuleModuleNotFoundError(
                        f"Module named {module_name!r} is not allowed by a rule"
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

        # Delegate to the rest of the chain to find the _original module spec
        # We skip our own finder by checking sys.meta_path from the next index
        # import builtins;builtins.print(f"finder {fullname}")
        for finder in sys.meta_path:
            if finder == self:
                continue
            original_spec: importlib.util.spec_from_file_location = finder.find_spec(
                fullname, path, target)
            if original_spec:
                break
        else:
            return None
            # if not original_spec:
            #     if fullname in "sys.modules":
            #         original_spec = sys.modules[fullname].__spec__
        if original_spec:
            # logger.debug(
            #     f"GuardFinder: Found _original spec via {type(finder).__name__!r}.")
            # Create a new spec using our custom GuardLoader, but with the _original spec's data

            # logger.debug(
            #     f"GuardFinder: Found _original spec {original_spec.name} via {type(finder).__name__!r}.")
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
            if is_learning_mode() and is_in_sandbox():
                module_name = fullname.split('.', 1)[0]
                if module_name not in _rules and module_name != "pysandboxes":
                    add_learning_rule(LearnImportRule(module_name))
            else:
                # logger.error("Ignore %s",repr(fullname))
                pass
            if fullname == "pysandboxes_run":
                logger.error(f"Pour pysandboxes_run {new_spec=}")
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

        sys.meta_path.insert(0, _guard_finder)
        return True
    else:
        logger.debug("Guard_import was already activated.")
        return False


# Modules to not remove from sys.modules, and to wait the lazy patch
_not_refresh_modules: Set[str] = (
    {
        'asyncio',
        'builtins',
        'concurrent',
        'importlib',
        'warnings',
        'logging',
        '_pytest',
        'pytest',
        'pathlib',
        'subprocess',
        __name__.rsplit('.', maxsplit=1)[0],
    }
)


def remove_modules() -> None:
    import sys
    to_remove = set()
    for k, m in dict(sys.modules).items():
        # Detect system modules
        for special in _not_refresh_modules:
            if k == special or k.startswith(special + "."):
                break
        else:
            to_remove.add(k)

    importlib.invalidate_caches()
    # Reload modules (may add modules with relead() )
    for k in to_remove:
        if k in sys.modules:
            if k in sys.builtin_module_names:
                m = sys.modules[k]
                if m:
                    importlib.reload(m)
                    pass

    # Remove modules
    for k in to_remove:
        if k in sys.modules:
            if k not in sys.builtin_module_names:
                del sys.modules[k]
    assert "io" not in sys.modules
#
# FIXME: remove version
# _not_refresh_modules: Set[str] = (
#     {
#         'importlib',
#         'concurrent',
#         'asyncio',
#         'warnings',
#         'logging',
#         '_pytest',
#         'pytest',
#         __name__.rsplit('.', maxsplit=1)[0],
#     }  # | set(sys.builtin_module_names)
# )
#
# # sys.builtin_module_names
# xx = ('_abc', '_ast', '_codecs', '_collections', '_functools', '_imp', '_io', '_locale',
#       '_operator', '_signal',
#       '_sre', '_stat', '_string', '_suggestions', '_symtable', '_sysconfig', '_thread',
#       '_tokenize', '_tracemalloc',
#       '_typing', '_warnings', '_weakref',
#       # 'atexit',
#       'builtins',
#       # 'errno',
#       # 'faulthandler',
#       # 'gc',
#       # 'itertools',
#       # 'marshal',
#       # 'posix',
#       # 'pwd',
#       'sys',
#       # 'time'
#       )
#
#
# def remove_modules() -> None:
#     import sys
#     to_remove = set()
#     for k, m in dict(sys.modules).items():
#         # Detect system modules
#         if k in xx:  # Il y a builtins
#             continue
#         for special in _not_refresh_modules:
#             if k == special or k.startswith(special + "."):
#                 break
#         else:
#             to_remove.add(k)
#
#     importlib.invalidate_caches()
#     # Reload modules (may add modules with relead() )
#     for k in to_remove:
#         if k in sys.modules:
#             if k in sys.builtin_module_names:
#                 m = sys.modules[k]
#                 if m:
#                     importlib.reload(m)
#                     pass
#
#     # Remove modules
#     for k in to_remove:
#         if k in sys.modules:
#             if k not in sys.builtin_module_names:
#                 del sys.modules[k]
#
#     # Merge remove modules
#     # for k in to_remove:
#     #     if k in sys.modules:
#     #         if k in sys.builtin_module_names:
#     #             m = sys.modules[k]
#     #             if m:
#     #                 importlib.reload(m)
#     #                 pass
#     #         else:
#     #             del sys.modules[k]
#     # Tricky: if you use debugger, the io are reinjected
#     assert "io" not in sys.modules


def patch_rules() -> Dict[str, Callable]:
    return {}


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




def _group_by_width(items: Iterable[str], max_width: int) -> List[str]:
    """
    Groups a list of strings by joining them with commas, respecting a maximum width.

    Args:
        items: The list of strings to group.
        max_width: The maximum allowed width for each group.

    Returns:
        A list of strings, where each string is a comma-separated group.
    """
    if not items:
        return []

    grouped_items: List[str] = []
    current_line: str = ""

    for item in items:
        # Check if a new line is needed
        if not current_line:
            current_line = item
        else:
            # Check if adding the new item exceeds the max width
            # We add 2 to the length for the comma and space
            if len(current_line) + len(item) + 2 <= max_width:
                current_line += ", " + item
            else:
                # Add the current line to the list and start a new one
                grouped_items.append(current_line)
                current_line = item

    # Append the last line if it's not empty
    if current_line:
        grouped_items.append(current_line)

    return grouped_items


def generate_rules(
        learn: Set[Any],
) -> List[str]:
    # FIXME: fichier pour std package FIXME: windows path
    # Select only parent
    other_result = set()
    standard_result = {
        "socket"  # Pre-selection for daemon
    }
    deprecated_result = set()
    danger_result = set()
    black_list = set(resources.read_text(__name__, "modules_blacklist.txt").split())
    std_modules = set(resources.read_text(__name__, "modules_standard.txt").split())
    deprecated_modules = set(resources.read_text(__name__, "modules_deprecated.txt").split())
    # Classify rules
    for learn_rule in filter(lambda x: isinstance(x, LearnImportRule), learn):
        if learn_rule.name in black_list:
            danger_result.add(learn_rule.name)
        elif learn_rule.name in std_modules or learn_rule.name[0] == "_":
            standard_result.add(learn_rule.name)
        elif learn_rule.name in deprecated_modules or learn_rule.name[0] == "_":
            deprecated_result.add(learn_rule.name)
        else:
            other_result.add(learn_rule.name)

    # generate rules
    width = 70
    result = []
    if danger_result:
        result.append("# \u26A0 Dangerous!")
        result.extend(sorted(
            [f"python-import={name}"
             for name in _group_by_width(sorted(danger_result), width)]))
        result.append("")
    if standard_result:
        result.append("# Standard Python")
        result.extend(sorted(
            [f"python-import={name}"
             for name in _group_by_width(sorted(standard_result), width)]))
        result.append("")
    if deprecated_result:
        result.append("# \u26A0 Deprecated Python module")
        result.extend(sorted(
            [f"python-import={name}"
             for name in _group_by_width(sorted(deprecated_result), width)]))
        result.append("")
    if other_result:
        result.append("# External modules (Are you sure about the origin?)")
        result.extend(sorted(
            [f"python-import={name}"
             for name in sorted(other_result)]))
    return result


if "PYTEST_RUN_CONFIG" in os.environ:
    def _deactivate_guard_import():
        import sys
        global _rules
        _rules = ()
        remove_modules()
