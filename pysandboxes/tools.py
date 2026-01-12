import re
from pathlib import Path
from typing import List, Dict


def substitute_env_vars(lines: List[str], env_vars: Dict[str, str]) -> List[str]:
    """
    The function supports two substitution formats:
    1. ${VAR_NAME}: Replaces the placeholder with the value of VAR_NAME from
       the env_vars dictionary. If the variable is not found, it's replaced
       with an empty string.
    2. ${VAR_NAME:-default_value}: Replaces the placeholder with the value of
       VAR_NAME if it exists in env_vars. Otherwise, it uses the provided
       default_value.

    """
    # This regular expression is designed to find all occurrences of the
    # ${...} pattern.
    # - Group 1 ([a-zA-Z0-9_]+): Captures the variable name. It consists of
    #   one or more alphanumeric characters or underscores.
    # - Group 2 (?:=...): Is an optional non-capturing group for the default value.
    # - Group 3 (.*?): Captures the default value itself, if present.
    #   The '?' makes the default value group optional.
    pattern = re.compile(r"\$\{([a-zA-Z0-9_]+)(?::=(.*?))?\}")

    def substitute(match: re.Match) -> str:
        """
        This nested function is called by re.sub for each match found.
        It performs the actual replacement logic.
        """
        var_name = match.group(1)
        default_value = match.group(2)  # This will be None if no default is provided

        # Use the variable from env_vars if it exists.
        # Otherwise, use the captured default_value.
        # If default_value is also None (the :- part was absent),
        # this expression results in an empty string.
        return env_vars.get(var_name,
                            default_value if default_value is not None else "")

    return [pattern.sub(substitute, line) for line in lines]


def read_config(
        path: Path,
) -> List[str]:
    """
    Reads a file, filters out empty lines and comments, and performs variable
    substitution on the remaining lines.

    Args:
        path: The Path object pointing to the file to be read.
        env_vars: A dictionary containing the environment-like variables
                  for substitution.

    Returns:
        A list of strings, where each string is a processed and substituted
        line from the file.
    """

    processed_lines: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            # We filter out empty lines and lines that are comments (start with #)
            if stripped and not stripped.lstrip().startswith("#"):
                # Apply the substitution to the valid line before appending it
                processed_lines.append(line.strip())

    return processed_lines


