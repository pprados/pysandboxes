# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Python import guard for PySandboxes.

This module implements import sandboxing by intercepting and controlling module
imports. It provides a whitelist-based security model where only explicitly
allowed modules can be imported.

The guard patches the import system using custom meta finders and loaders to
enforce import restrictions defined in the configuration. It supports pattern
matching and learning mode for automatic rule generation.
"""

import importlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import importlib.util
import itertools
import logging
import os
import sys
from copy import copy
from importlib import resources
from importlib.abc import Loader
from importlib.machinery import ModuleSpec
from importlib.metadata import DistributionFinder
from types import ModuleType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterable,
    Iterator,
    MutableMapping,
    NamedTuple,
    Sequence,
    cast,
)

from .e import RuleModuleNotFoundError
from .immutable_dict import ImmutableDict
from .learning import add_learning_rule, is_learning_mode
from .main_logger import ErrorMsg
from .sb_types import ConfigLines
from .tools import is_in_sandbox

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from importlib.metadata import FastPath, Prepared  # type: ignore[attr-defined]

    from _typeshed.importlib import MetaPathFinderProtocol
else:
    Prepared = Any
    FastPath = Any
    MetaPathFinderProtocol = Any


class PatchRule(NamedTuple):
    """Rule for applying patches to imported modules.

    Attributes:
        code_path: Name of the module or attribute to patch.
        patch_factory: Factory function that creates the patch.
    """

    code_path: str
    patch_factory: Callable


PatchRules = ImmutableDict[str, tuple[PatchRule, ...]]

ImportRules = tuple[str, ...]


class LearnImportRule(NamedTuple):
    """Learning rule for tracking imported modules.

    Attributes:
        name: Name of the imported module.
    """

    name: str


def _conv_patch_rules(patch_rules: dict[str, Callable]) -> PatchRules:
    """Convert patch rules dictionary to structured patch rules.

    Args:
        patch_rules: Dictionary mapping module paths to patch factories.

    Returns:
        Structured patch rules organized by top-level module.
    """
    rules: MutableMapping[str, list[PatchRule]] = {}
    # Split path by first module
    for k, v in patch_rules.items():
        if "." in k:
            module, path = k.split(".", maxsplit=1)
        else:
            module, path = k, ""
        patch_list: list[PatchRule] = rules.get(module, [])
        patch_list.append(PatchRule(path, v))
        rules[module] = patch_list

    return PatchRules({k: tuple(v) for k, v in rules.items()})


_rules: ImportRules = cast(ImportRules, ())
_patch_rules: PatchRules = ImmutableDict({})


def parse_rules(
    config: ConfigLines,
    errors: list[ErrorMsg],
) -> tuple[ImportRules, ConfigLines]:
    """Parse import rules from configuration lines.

    Args:
        config: Configuration lines to process.
        errors: List to collect parsing errors.

    Returns:
        Tuple of parsed import rules and remaining config lines.
    """
    white_list: list[str] = []
    ignore_rules: ConfigLines = []
    for rule in config:
        if rule.rule.startswith("python-import="):
            value = rule.rule.split("=", 1)[1]
            # Accept multiple --python-import rules
            white_list.extend([r.strip() for r in value.split(",")])
        else:
            ignore_rules.append(rule)
    if "*" in white_list:
        white_list = ["*"]
    return tuple(white_list), ignore_rules


def _apply_patch(module: ModuleType, name: str) -> None:
    """Apply patches to a loaded module.

    Args:
        module: The loaded module to patch.
        name: Name of the module being patched.
    """
    # logger.debug(f"Apply patch for {module.__name__}")
    all_patch = cast(tuple[PatchRule, ...], _patch_rules[name])
    for patch in all_patch:
        cur_object = module
        if patch.code_path != "":
            paths = patch.code_path.split(".")
            for node in paths[:-1]:
                cur_object = cur_object.__dict__[node]
            original_value = getattr(cur_object, paths[-1])
            # FIXME # Skip if already patched
            # if hasattr(original_value, "__pysandbox__"):
            #     continue
            new_value = patch.patch_factory(original_value)
            assert not hasattr(new_value, "__pysandbox__"), "Double injection"
            if __debug__ and isinstance(
                new_value, type(_apply_patch)
            ):  # Fake kinds.FunctionType
                new_value.__pysandbox__ = True  # type: ignore[attr-defined]
            setattr(cur_object, paths[-1], new_value)
            # logger.debug("Patch %s.%s",name, patch.code_path)
        else:
            # Patch the entire module
            sys.modules[name] = patch.patch_factory(cur_object)
            # logger.debug("Patch the module %s",name)


class GuardLoader(Loader):
    """Custom loader that wraps original loader to modify modules after loading.

    This loader intercepts the module loading process to enforce import restrictions
    and apply patches to modules as they are loaded.
    """

    __slots__ = ("fullname", "original_spec", "original_loader", "original_module")

    def __init__(
        self,
        fullname: str,
        original_spec: ModuleSpec | None,
        module: ModuleType | None = None,
    ):
        """Initialize the guard loader.

        Args:
            original_spec: The original module specification to wrap.
        """
        # Store the _original spec and loader
        self.fullname = fullname
        self.original_spec = original_spec
        self.original_loader = original_spec.loader if original_spec else None
        self.original_module = module

    def create_module(self, spec: ModuleSpec) -> ModuleType | None:
        """Delegate module creation to the original loader.

        Args:
            spec: Module specification.

        Returns:
            Created module or None if creation failed.
        """
        # logger.debug(f"create_module({spec=}")
        if self.original_loader is None:
            return None
        if self.original_module:
            return self.original_module
        assert self.original_spec, f"No original spec for {self.fullname=}"
        module = self.original_loader.create_module(self.original_spec)
        return module  # Not initialized

    def exec_module(self, module: ModuleType) -> None:
        """Execute module code and apply custom modifications.

        Enforces import restrictions and applies patches after module execution.

        Args:
            module: Module to execute.

        Raises:
            RuleModuleNotFoundError: If module is not allowed by rules.
        """

        if module is None:
            return
        if not self.original_loader:
            return
        if self.original_module:
            # logger.debug("move original module %s", self.original_module.__name__)
            # Module is initialized
            to_delete = []
            for k, m in _pending_modules.items():
                if k.startswith(self.fullname + "."):
                    # logger.debug("move original module %s", k)
                    sys.modules[k] = m  # Reinject sub modules
                    to_delete.append(k)
            del _pending_modules[self.fullname]
            for k in to_delete:
                del _pending_modules[k]
            return

        # logger.debug(f"exec_module({module.__name__})...")
        self.original_loader.exec_module(module)

        # if not self.done and self.original_spec.name in _rules:
        if self.original_spec and self.original_spec.name in _patch_rules:
            _apply_patch(module, self.original_spec.name)


# Define the custom finder class
class GuardFinder(importlib.abc.MetaPathFinder):
    """Custom meta path finder that intercepts module imports.

    This finder wraps the standard import mechanism to enforce import
    restrictions and apply patches to modules during loading.
    """

    @classmethod
    def find_distributions(
        cls, context: DistributionFinder.Context | None = None
    ) -> Iterable[importlib.metadata.PathDistribution]:
        """Find package distributions.

        Args:
            context: Distribution finder context.

        Returns:
            Iterable of path distributions for matching packages.
        """
        from importlib.metadata import PathDistribution

        if context is None:
            context = DistributionFinder.Context()
        if context.name and context.path:
            found = cls._search_paths(context.name, context.path)
        else:
            found = iter([])
        return map(PathDistribution, found)

    @classmethod
    def _search_paths(cls, name: str | None, paths: list[str]) -> Iterator[FastPath]:
        """Find metadata directories in paths heuristically.

        Args:
            name: Package name to search for.
            paths: List of directory paths to search in.

        Returns:
            Iterator of FastPath objects for found metadata directories.
        """
        from importlib.metadata import FastPath, Prepared  # type: ignore[attr-defined]

        prepared = Prepared(name)
        return itertools.chain.from_iterable(
            path.search(prepared) for path in map(FastPath, paths)
        )

    __slots__ = ("_finders",)

    def __init__(self, finders: list[MetaPathFinderProtocol]):
        """Initialize the guard finder.

        Args:
            finders: List of meta path finders to delegate to.
        """
        self._finders = finders

    """
    A custom finder that locates our special module.
    """

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> ModuleSpec | None:
        """Find module specification with import guarding.

        Args:
            fullname: Fully qualified module name.
            path: Package path if this is a submodule.
            target: Target module for relative imports.

        Returns:
            Module specification with guard loader if applicable.
        """
        global _rules
        # logger.debug(f"find_spec({fullname=},{path=},{target=})")

        # Delegate to the rest of the chain to find the _original module spec
        # We skip our own finder by checking sys.meta_path from the next index
        # import builtins;builtins.print(f"finder {fullname}")
        global _pending_modules
        new_spec: ModuleSpec | None = None
        finder: MetaPathFinderProtocol = self
        if fullname in _pending_modules:
            # Find a module that was already present
            # Move it into sys.modules.
            pending_module = _pending_modules[fullname]

            module_name: str | None = None
            original_spec: ModuleSpec | None = pending_module.__spec__
            if original_spec and hasattr(original_spec, "name"):
                module_name = original_spec.name
            if not module_name:
                if hasattr(pending_module, "__name__"):
                    module_name = pending_module.__name__
                else:
                    module_name = fullname
            # Change the loader to move in the right place
            new_spec = importlib.machinery.ModuleSpec(
                name=module_name,
                loader=GuardLoader(fullname, original_spec, _pending_modules[fullname]),
                origin=original_spec.origin if original_spec else None,
                loader_state=original_spec.loader_state if original_spec else None,
            )
            original_spec = None

        else:
            for finder in sys.meta_path:
                if finder == self:
                    continue
                if original_spec := finder.find_spec(fullname, path, target):
                    break
            else:
                return None
        if original_spec:
            # logger.debug(
            #     f"GuardFinder: Found _original spec via {type(finder).__name__!r}."
            # )
            # Create a new spec using our custom GuardLoader,
            # but with the _original spec's data

            if original_spec.name in _patch_rules:
                # logger.debug(f"Inject loader for {original_spec.name!r}")
                if original_spec.parent:
                    # Use __init__
                    if original_spec.submodule_search_locations:
                        init_file = os.path.join(
                            original_spec.submodule_search_locations[0], "__init__.py"
                        )
                    else:
                        if original_spec.origin is None:
                            return None
                        init_file = original_spec.origin
                    assert os.path.isfile(init_file), "module without __init__.py"
                    # logger.debug(f"Inject loader for {original_spec.name!r}")
                    new_spec = importlib.util.spec_from_file_location(
                        fullname,
                        init_file,
                        loader=GuardLoader(fullname, original_spec, None),
                        submodule_search_locations=original_spec.submodule_search_locations,
                    )
                else:
                    new_spec = importlib.machinery.ModuleSpec(
                        name=original_spec.name,
                        loader=GuardLoader(fullname, original_spec, None),
                        origin=original_spec.origin,
                        loader_state=original_spec.loader_state,
                    )
            else:
                # return None # Let the next guy take care of it?
                if not new_spec:
                    new_spec = original_spec
        if new_spec:
            module_name = fullname.split(".", 1)[0]
            if is_learning_mode() and is_in_sandbox():
                if (
                    "*" not in _rules
                    and module_name not in _rules
                    and module_name != "pysandboxes"
                ):
                    add_learning_rule(LearnImportRule(module_name))
            else:
                if _rules and _rules[0] != "*":
                    # Reactiver le filtre de module
                    if (
                        not module_name.startswith("pysandboxes")
                        and module_name not in _rules
                    ):
                        ex = RuleModuleNotFoundError(
                            f"Module named {module_name!r} is not allowed by a rule"
                        )
                        try:
                            logger.debug(
                                "Module named %s is not allowed by a rule",
                                repr(module_name),
                            )
                        except RecursionError:
                            # Fall back if it's impossible to log the exception
                            # It's possible if the module for log is not in a rule.
                            print(
                                f"Module named {module_name!r} is not allowed by a rule",
                                file=sys.stderr,
                            )
                        raise ex
            return new_spec

        # For all other imports, return None to let the standard import
        # mechanism handle them
        return None


_pending_modules: dict[str, ModuleType] = {}
_guard_finder: importlib.abc.MetaPathFinder = GuardFinder(sys.meta_path)

_activated = False


def _activate_patch_import(
    patch_rules: PatchRules,
) -> bool:
    """Activate import patching with specified rules.

    Args:
        patch_rules: Rules for patching modules during import.

    Returns:
        True if patching was activated, False if already active.
    """
    global _activated
    import sys

    if _guard_finder not in sys.meta_path:
        global _patch_rules
        assert not _activated
        _patch_rules = patch_rules

        sys.meta_path.insert(0, _guard_finder)
        _activated = True
        return True
    else:
        logger.debug("Guard_import was already activated.")
        assert _activated
        return False


def patch_rules(learn: bool) -> dict[str, Callable]:
    """Get default patch rules for import guard.

    Returns:
        Dictionary mapping module paths to patch factory functions.
    """
    return {}


def activate_guard_import(
    str_patch_rules: dict[str, Callable],
    rules: ImportRules,
) -> None:
    """Activate import guard with specified rules and patches.

    Args:
        str_patch_rules: Dictionary mapping module paths to patch factories.
        rules: Import rules specifying allowed modules.
    """
    global _rules
    global _activated

    patch_rules: PatchRules = _conv_patch_rules(str_patch_rules)
    if _activated:
        logger.debug("Guard_files was already activated.")
        return

    # Save the current modules BEFORE patching
    global _pending_modules
    _pending_modules = copy(sys.modules)

    if _activate_patch_import(patch_rules):  # Add in sys.meta_path
        # For all loaded modules, apply patch
        for module in sys.modules.copy():  # FIXME: copy nécessaire ?
            if module in patch_rules:
                _apply_patch(sys.modules[module], module)
    keep = [
        "warnings",
        "tokenize",  # For assertion
        "asyncio",
        "sys",
        "threadpool",
        "builtins",
        "__main__",
    ]  # TODO: add in rules ?
    # logger.warning("NO DELETE MODULE")
    for k in _pending_modules:
        # logger.error("Remove %s", k)
        if k not in keep:
            del sys.modules[k]

    _rules = rules


def _group_by_width(items: Iterable[str], max_width: int) -> list[str]:
    """Group strings by joining with commas, respecting maximum width.

    Args:
        items: The strings to group.
        max_width: The maximum allowed width for each group.

    Returns:
        List of comma-separated grouped strings.
    """
    if not items:
        return []

    grouped_items: list[str] = []
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
                # Add the current line to the list and _start a new one
                grouped_items.append(current_line)
                current_line = item

    # Append the last line if it's not empty
    if current_line:
        grouped_items.append(current_line)

    return grouped_items


def generate_rules(
    learn: set[Any],
) -> list[str]:
    """Generate import rules from learning data.

    Categorizes learned imports into standard, deprecated, dangerous,
    and external modules to generate appropriate configuration rules.

    Args:
        learn: Set of learning rules collected during execution.

    Returns:
        List of configuration rule strings for imports.
    """
    # Select only parent
    other_result = set()
    standard_result = set()
    deprecated_result = set()
    danger_result = set()
    black_list = set(resources.read_text(__name__, "modules_blacklist.txt").split())
    std_modules = set(resources.read_text(__name__, "modules_standard.txt").split())
    deprecated_modules = set(
        resources.read_text(__name__, "modules_deprecated.txt").split()
    )
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
        result.append("# \u26a0 Dangerous!")
        result.extend(
            sorted(
                [
                    f"python-import={name}"
                    for name in _group_by_width(sorted(danger_result), width)
                ]
            )
        )
        result.append("")
    if standard_result:
        result.append("# Standard Python")
        result.extend(
            sorted(
                [
                    f"python-import={name}"
                    for name in _group_by_width(sorted(standard_result), width)
                ]
            )
        )
        result.append("")
    if deprecated_result:
        result.append("# \u26a0 Deprecated Python module")
        result.extend(
            sorted(
                [
                    f"python-import={name}"
                    for name in _group_by_width(sorted(deprecated_result), width)
                ]
            )
        )
        result.append("")
    if other_result:
        result.append("# External modules (Are you sure about the origin?)")
        result.extend(
            sorted([f"python-import={name}" for name in sorted(other_result)])
        )
    return result


if "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules:

    def _deactivate_guard_import() -> None:
        """Deactivate import guard and restore original state.

        This function completely restores the Python import system to its state
        before activation, including:
        - Removing the guard finder from sys.meta_path
        - Restoring all modules to sys.modules from _pending_modules
        - Resetting activation flags

        Note: Modules that are kept in sys.modules (builtins, warnings, etc.)
        are not restored to avoid conflicts with patched versions.
        """
        global _rules, _activated, _pending_modules, _patch_rules

        # Remove guard finder from sys.meta_path
        if _guard_finder in sys.meta_path:
            sys.meta_path.remove(_guard_finder)

        # Restore pending modules back to sys.modules, except those that were kept
        keep = [
            "warnings",
            "tokenize",
            "asyncio",
            "sys",
            "threadpool",
            "builtins",
            "__main__",
        ]

        if _pending_modules:
            for module_name, module in _pending_modules.items():
                # Only restore modules that were removed from sys.modules
                if module_name not in keep and module_name not in sys.modules:
                    sys.modules[module_name] = module
            _pending_modules = {}

        # Reset flags and rules
        _rules = ("*",)
        _activated = False
        _patch_rules = ImmutableDict({})
