import re
from typing import Dict, Optional

from .types import ConfigLines


def substitute_env_vars(lines: ConfigLines, env_vars: Dict[str, str]) -> ConfigLines:
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


def remove_comments(config: ConfigLines) -> ConfigLines:
    processed_lines: ConfigLines = []

    for line in config:
        # Remove end-of-line comments while respecting quotes
        cleaned_line: str = _remove_comment(line.strip())

        # Filter out empty lines and lines that are full comments
        if cleaned_line and not cleaned_line.lstrip().startswith("#"):
            processed_lines.append(cleaned_line)

    return processed_lines


def _remove_comment(line: str) -> str:
    """
    Removes comments from a line while respecting quotes.

    Args:
        line: The line to process

    Returns:
        Line without comment
    """
    result: ConfigLines = []
    in_quotes: bool = False
    quote_char: Optional[str] = None
    i: int = 0

    while i < len(line):
        char: str = line[i]

        # Handle quotes (single or double)
        if char in ['"', "'"] and not in_quotes:
            in_quotes = True
            quote_char = char
            result.append(char)
        elif char == quote_char and in_quotes:
            # Check if the quote is escaped
            if i > 0 and line[i - 1] == '\\':
                result.append(char)
            else:
                in_quotes = False
                quote_char = None
                result.append(char)
        # If we find a # and we're not inside quotes
        elif char == '#' and not in_quotes:
            # Stop here, this is the start of the comment
            break
        else:
            result.append(char)

        i += 1

    # Remove trailing whitespace
    return ''.join(result).rstrip()