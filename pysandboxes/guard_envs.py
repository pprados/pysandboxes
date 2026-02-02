import logging
import os
import re
from pathlib import Path
from typing import Dict, Tuple, List, Any, Optional, Callable, NamedTuple, cast

from .main_logger import format_ruleref, ErrorMsg
from .types import ConfigLines, ConfigLine, Envs

logger = logging.getLogger(__name__)


# Internal representation of a rule
class EnvRule(NamedTuple):
    pattern: re.Pattern
    ignore: bool
    config: ConfigLine


EnvsRules = Tuple[EnvRule, ...]

# Internal state for the file filter
_rules: EnvsRules = cast(EnvsRules, ())

def _read_and_substitute_lines(
        path: Path, env_vars: Dict[str, str]
) -> ConfigLines:
    """
    Reads a file, filters out empty lines and comments, and performs variable
    substitution on the remaining lines.

    The function supports two substitution formats:
    1. ${VAR_NAME}: Replaces the placeholder with the value of VAR_NAME from
       the env_vars dictionary. If the variable is not found, it's replaced
       with an empty string.
    2. ${VAR_NAME:=default_value}: Replaces the placeholder with the value of
       VAR_NAME if it exists in env_vars. Otherwise, it uses the provided
       default_value.

    Args:
        path: The Path object pointing to the file to be read.
        env_vars: A dictionary containing the environment-like variables
                  for substitution.

    Returns:
        A list of strings, where each string is a processed and substituted
        line from the file.
    """
    pattern = re.compile(r"\$\{([a-zA-Z0-9_]+)(?::=(.*?))?\}")

    def substitute(match: re.Match) -> str:
        var_name = match.group(1)
        default_value = match.group(2)
        return env_vars.get(var_name,
                            default_value if default_value is not None else "")

    processed_lines: ConfigLines = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.lstrip().startswith("#"):
                substituted_line = pattern.sub(substitute, stripped)
                processed_lines.append(substituted_line)
    return processed_lines


def parse_rules(
        rules: ConfigLines,
        source_vars: Dict[str, str],
        errors: List[ErrorMsg],
) -> Tuple[EnvsRules, Envs, ConfigLines]:
    """
    Processes a list of socket_rules to create a new dictionary of variables.

    Args:
        rules: A list of rule strings, e.g., ["key=value", "key2=${source_key}"].
        source_vars: The original dictionary of variables to draw from.

    Returns:
        A new dictionary with the applied socket_rules.
    """
    new_vars: Dict[str, str] = {}
    ignore_rules: ConfigLines = []

    # This pattern finds ${VAR} or ${VAR:=default} substitutions.
    subst_pattern = re.compile(r"\$\{([a-zA-Z0-9_]+)(?::=(.*?))?\}")

    def substitute_value(value_pattern: str) -> str:
        """Resolves a single value pattern, e.g., ${VAR:=default}."""
        return subst_pattern.sub(
            lambda m: source_vars.get(m.group(1),
                                      m.group(2) if m.group(2) is not None else ""),
            value_pattern
        )

    envs_rules = set()
    for orule in rules:
        if orule.rule.startswith("--set-env="):
            # Remove prefix
            rule = ConfigLine(orule.rule[len("--set-env="):], orule.path, orule.ln)

            if "=" not in rule.rule:
                errors.append(
                    (
                        f"{format_ruleref(orule)}: "
                        f"Detect a missing '=' in rule: {orule.rule}.",
                        rule.path,
                        rule.ln
                    )
                )
                continue

            key_pattern, value_pattern = rule.rule.split("=", 1)

            # Case: Wildcard rule like *_API_KEY=${*_API_KEY}
            if "*" in key_pattern:
                # Convert wildcard to regex pattern
                regex_key = re.compile(
                    re.escape(key_pattern).replace("\\*", ".*"))
                envs_rules.add(EnvRule(regex_key, False, orule))
                for source_key, source_value in source_vars.items():
                    if regex_key.match(source_key):
                        # The rule implies copying the matched key-value pairs
                        new_vars[source_key] = source_value
            # Case: Simple rule like key=value or key=${VAR}
            else:
                new_vars[key_pattern] = substitute_value(value_pattern)
                envs_rules.add(EnvRule(re.compile(re.escape(key_pattern)), False, orule))
        elif orule.rule.startswith("--unset-env="):
            remove_key = orule.rule[len("--unset-env="):]
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

    _instance: 'LearnEnviron' = None

    def __new__(cls,
                ) -> 'LearnEnviron':
        # Implement a singleton
        if cls._instance is None:
            cls._instance = super(LearnEnviron, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # Initialize with the original environment data
        if not hasattr(self, '_keys_used'):
            # super().__init__(original_environ)
            encodekey = os.environ.encodekey
            decodekey = os.environ.decodekey
            encodevalue = os.environ.encodevalue
            decodevalue = os.environ.decodevalue
            data = os.environ._data
            super().__init__(data, encodekey, decodekey, encodevalue, decodevalue)
            self._keys_used = set()
            self._original_envs = dict(os.environ)

    def __getitem__(self, key: str) -> str:
        try:
            result = super(LearnEnviron, self).__getitem__(key)
            self._keys_used.add(key)
            return result
        except KeyError:
            raise

    def __setitem__(self, key: str, value: str) -> None:
        super(LearnEnviron, self).__setitem__(key, value)
        self._keys_used.add(key)

    def _clone(self):
        return {k: v for k, v in super().items()}

    def _get(self, key: str, default: Any = None) -> Any:
        try:
            result = super(LearnEnviron, self).__getitem__(key)
            return result
        except KeyError:
            return default


def generate_rules(
) -> List[str]:
    global _rules
    learn_env = LearnEnviron()  # Get singleton
    result = []
    for key in sorted(learn_env._keys_used):
        find = False
        for pat in _rules:
            if pat.pattern.match(key):
                find=True
                break
        if not find:
            result.append(f"--set-env={key}=$({key})")
    return result

def activate_guard(
        rules: EnvsRules
) -> None:
    global _rules
    _rules=rules


def patch_rules(learning_path: Optional[Path]) -> Dict[str, Callable]:
    if learning_path:
        def activate_learning_env_factory(x):
            return LearnEnviron()

        return {"os.environ": activate_learning_env_factory}
    else:
        return {}
