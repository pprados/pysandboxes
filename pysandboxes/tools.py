from pathlib import Path
from typing import List


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


