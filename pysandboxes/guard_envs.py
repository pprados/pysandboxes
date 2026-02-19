import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, NamedTuple, Optional, Set, Tuple, cast

from .main_logger import ErrorMsg, format_ruleref
from .sb_types import ConfigLine, ConfigLines, Envs
from .tools import Environ, is_in_sandbox, resolve_env_variables

logger = logging.getLogger(__name__)


# Internal representation of a rule
class EnvRule(NamedTuple):
    pattern: re.Pattern
    ignore: bool
    config: ConfigLine


EnvsRules = Tuple[EnvRule, ...]

# Internal state for the file filter
_rules: EnvsRules = cast(EnvsRules, ())


def parse_rules(
    rules: ConfigLines,
    source_vars: Environ,
    errors: List[ErrorMsg],
) -> Tuple[EnvsRules, Envs, ConfigLines]:
    """
    Processes a list of rules to create a new dictionary of variables.

    Args:
        rules: A list of rule strings, e.g., ["key=value", "key2=${source_key}"].
        source_vars: The _original dictionary of variables to draw from.

    Returns:
        A new dictionary with the applied rules.
    """
    new_vars: Dict[str, str] = {}
    ignore_rules: ConfigLines = []

    def substitute_value(value_pattern: str) -> str:
        return resolve_env_variables(value_pattern, source_vars)

    envs_rules = set()
    for orule in rules:
        if orule.rule.startswith("env="):
            # Remove prefix
            rule = ConfigLine(orule.rule[len("env=") :], orule.path, orule.ln)

            if "=" not in rule.rule:
                errors.append(
                    (
                        f"{format_ruleref(orule)}: "
                        f"Detect a missing '=' in rule: {orule.rule}.",
                        rule.path,
                        rule.ln,
                    )
                )
                continue

            key_pattern, value_pattern = rule.rule.split("=", 1)

            # Case: Wildcard rule like *_API_KEY=${*_API_KEY}
            if "*" in key_pattern:
                # Convert wildcard to regex pattern
                regex_key = re.compile(re.escape(key_pattern).replace("\\*", ".*"))
                envs_rules.add(EnvRule(regex_key, False, orule))
                for source_key, source_value in source_vars.items():
                    if regex_key.match(source_key):
                        # The rule implies copying the matched key-value pairs
                        new_vars[source_key] = source_value
            # Case: Simple rule like key=value or key=${VAR}
            else:
                new_vars[key_pattern] = substitute_value(value_pattern)
                envs_rules.add(
                    EnvRule(re.compile(re.escape(key_pattern)), False, orule)
                )
        elif orule.rule.startswith("unenv="):
            remove_key = orule.rule[len("unenv=") :]
            new_vars.pop(remove_key, None)
            envs_rules.add(EnvRule(re.compile(re.escape(remove_key)), True, orule))
        else:
            ignore_rules.append(orule)

    return tuple(envs_rules), Envs(new_vars), ignore_rules


class LearnEnviron(os._Environ):
    # """
    # A custom class that replaces os.environ to log all accesses,
    # while behaving like a standard dictionary.
    # """

    _instance: Optional["LearnEnviron"] = None

    def __new__(
        cls,
    ) -> "LearnEnviron":
        # Implement a singleton
        if cls._instance is None:
            cls._instance = super(LearnEnviron, cls).__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # Initialize with the _original environment data
        if not hasattr(self, "_keys_used"):
            # super().__init__(original_environ)
            encodekey = os.environ.encodekey
            decodekey = os.environ.decodekey
            encodevalue = os.environ.encodevalue
            decodevalue = os.environ.decodevalue
            assert hasattr(os.environ, "_data")
            data = os.environ._data  # type: ignore[attr-defined]
            super().__init__(data, encodekey, decodekey, encodevalue, decodevalue)
            self._keys_used: Set[str] = set()
            self._original_envs = os.environ

    def __getitem__(self, key: str) -> str:
        try:
            result = super(LearnEnviron, self).__getitem__(key)
            if is_in_sandbox():
                self._keys_used.add(key)
            return result
        except KeyError:
            raise

    def __setitem__(self, key: str, value: str) -> None:
        super(LearnEnviron, self).__setitem__(key, value)
        if is_in_sandbox():
            self._keys_used.add(key)

    def _clone(self) -> Dict[str, str]:
        return {k: v for k, v in super().items()}

    def _get(self, key: str, default: Any = None) -> Any:
        try:
            result = super(LearnEnviron, self).__getitem__(key)
            return result
        except KeyError:
            return default

    def _has(self, key: str) -> Any:
        try:
            super(LearnEnviron, self).__getitem__(key)
            return True
        except KeyError:
            return False


def generate_rules() -> List[str]:  # TODO: search in envs for url, port, etc.
    global _rules
    learn_env = LearnEnviron()  # Get singleton
    result = []
    for key in sorted(learn_env._keys_used):
        find = False
        for pat in _rules:
            if pat.pattern.match(key):
                find = True
                break
        if not find:
            result.append(f"env={key}=${{{key}}}")
    return result


def activate_guard(rules: EnvsRules) -> None:
    global _rules
    _rules = rules


def patch_rules(learning_path: Optional[Path]) -> Dict[str, Callable]:
    if learning_path:

        def activate_learning_env_factory(x: Any) -> LearnEnviron:
            return LearnEnviron()

        return {"os.environ": activate_learning_env_factory}
    else:
        return {}
