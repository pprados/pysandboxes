import inspect
import logging
import os
import re
import sys
import types
from importlib.resources import files, as_file
from pathlib import Path
from typing import Optional, List, Dict

from . import guard_files, guard_env
from . import guard_socket

logger = logging.getLogger(__name__)


def get_caller_module(skip: int = 2) -> Optional[types.ModuleType]:
    """
    Returns the module of the caller.

    Parameters:
        skip (int): How many stack frames to skip.
                    skip=0 -> current function (get_caller_module),
                    skip=1 -> function calling get_caller_module,
                    skip=2 -> caller of that function (default).

    Returns:
        ModuleType | None: The module object of the caller, or None if not found.
    """
    frame = inspect.currentframe()
    for _ in range(skip):
        if frame is not None:
            frame = frame.f_back
    if frame is not None:
        module = inspect.getmodule(frame)
        return module
    return None


def _read_config(
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
                processed_lines.append(line)

    return processed_lines


def _substitute_env_vars(lines: List[str], env_vars: Dict[str, str]) -> List[str]:
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
    # - Group 2 (?:-...): Is an optional non-capturing group for the default value.
    # - Group 3 (.*?): Captures the default value itself, if present.
    #   The '?' makes the default value group optional.
    pattern = re.compile(r"\$\{([a-zA-Z0-9_]+)(?::\-(.*?))?\}")

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


def activate_sandboxes(
        envs: Dict[str, str] = os.environ,
        args_rules:Optional[List[str]]=None) -> None:

    # 1. try to find .pysandboxes in the caller module
    if args_rules is None:
        args_rules = []
    body_from_ressource = []
    # FIXME: a bug in importlib.resources.files
    # caller_module = get_caller_module()
    # if caller_module:
    #     resource = files(caller_module.__name__).joinpath(".pysandboxes")
    #     # resource = files(caller_module.__package__).joinpath(".pysandboxes")
    #     if resource.exists():
    #         with as_file(resource) as path:
    #             body_from_ressource = _read_config(path)

    # 2. try to find .pysandboxes in special directories
    known_paths = [
        Path(".pysandboxes"),  # Current directory
        Path("~/.config/pysandboxes/pysandboxes").expanduser(),
        Path("~/.local/share/pysandboxes/pysandboxes").expanduser(),
        Path("/etc/pysandboxes/pysandboxes"),
        Path("/usr/share/pysandboxes/pysandboxes"),
        Path("/var/lib/pysandboxes/pysandboxes"),
    ]
    body_from_users_or_os = []
    for path in known_paths:
        if path.exists():
            body_from_users_or_os = _read_config(path)
            break
    # 3. Merge all files
    rules = body_from_ressource + args_rules + body_from_users_or_os

    # 4. Parse the rules, step by step
    sandbox_env, others =guard_env.parse_guard_envs(rules, envs)
    others = _substitute_env_vars(others, envs)
    socket_rules, others = guard_socket.parse_rules(others)
    files_rules, others = guard_files.parse_rules(others)

    # 5. If some line are ignored, log a warning
    if others:
        for invalide_rule in others:
            logger.warning(f"Ignore invalid rule: {invalide_rule}")

    # 6. Apply the rules
    os.environ=sandbox_env
    guard_socket.activate_guard_socket(socket_rules)
    guard_files.activate_guard_files(files_rules)


