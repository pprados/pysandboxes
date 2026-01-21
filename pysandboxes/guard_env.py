import logging
import re
from pathlib import Path
from typing import Dict, Tuple, List

from .main_logger import format_ruleref, ErrorMsg
from .types import ConfigLines, ConfigLine

logger = logging.getLogger(__name__)


# TODO: déplacer les guard_* dans un module dédié
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


def parse_guard_envs(
        rules: ConfigLines,
        source_vars: Dict[str, str],
        errors: List[ErrorMsg],
) -> Tuple[Dict[str, str], ConfigLines]:
    """
    Processes a list of rules to create a new dictionary of variables.

    Args:
        rules: A list of rule strings, e.g., ["key=value", "key2=${source_key}"].
        source_vars: The original dictionary of variables to draw from.

    Returns:
        A new dictionary with the applied rules.
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
                for source_key, source_value in source_vars.items():
                    if regex_key.match(source_key):
                        # The rule implies copying the matched key-value pairs
                        new_vars[source_key] = source_value
            # Case: Simple rule like key=value or key=${VAR}
            else:
                new_vars[key_pattern] = substitute_value(value_pattern)
        elif orule.rule.startswith("--unset-env="):
            remove_key = orule.rule[len("--unset-env="):]
            new_vars.pop(remove_key, None)
        else:
            ignore_rules.append(orule)

    return new_vars, ignore_rules
