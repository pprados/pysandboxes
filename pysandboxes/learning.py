# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Learning mode implementation for automatic rule generation.

This module implements the learning mode functionality that observes sandbox
behavior and automatically generates security rules based on observed file access,
network connections, imports, and environment variable usage.

Learning mode helps developers bootstrap sandbox configurations by running their
application through typical usage scenarios and capturing required permissions.
"""

import logging
import re
import threading
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any, Set

from .config import DEBUG
from .main_logger import make_relative_path, pysandboxes_logger

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_learning: Set[Any] = set()

_learning_path: Path | None = None
_learning_mode: bool = False

# Check double usage
_lock_generate = threading.Lock()
_save_learning_done: bool = False


def generate_config_from_learning() -> None:
    """Generate configuration file from observed learning rules.

    This function consolidates all rules collected during learning mode and
    writes them to a configuration file. It handles rule formatting, template
    processing, and file backup operations.
    """
    global _learning_path, _save_learning_done, _lock
    if not is_learning_mode():
        return
    with _lock_generate:
        from .guard_envs import generate_rules as env_generate_rules
        from .guard_files import generate_rules as file_generate_rules
        from .guard_import import generate_rules as import_generate_rules
        from .guard_socket import generate_rules as socket_generate_rules

        with _lock:
            learning = _learning.copy()
        # Manage old files
        if _save_learning_done:
            return

        learning_path = _learning_path
        assert learning_path
        learning_path, old_learning_path = _manage_olds_file(learning_path)
        logger.debug(
            "generate_config_from_learning(%s,%s)",
            make_relative_path(learning_path),
            make_relative_path(old_learning_path),
        )

        # Manage envs rules
        env_rules = env_generate_rules()
        if env_rules:
            all_env_rules = "\n".join(env_rules)
        else:
            all_env_rules = ""

        # Manage import rules
        import_rules = import_generate_rules(learning)
        if import_rules:
            all_import_rules = "\n".join(import_rules)
        else:
            all_import_rules = ""

        # Manage files rules
        file_rules = file_generate_rules(learning)
        if file_rules:
            all_file_rules = "\n".join(file_rules)
        else:
            all_file_rules = ""

        # Manage sockets rules
        socket_rules = socket_generate_rules(learning)
        if socket_rules:
            all_socket_rules = "\n".join(socket_rules)
        else:
            all_socket_rules = ""

        replaces: dict[str, str] = {
            # "learning_repeat": f"learn={learning_path}",
            "learning_guard_envs": all_env_rules,
            "learning_guard_import": all_import_rules,
            "learning_guard_files": all_file_rules,
            "learning_guard_socket": all_socket_rules,
        }

        header = f"# Add rules ({datetime.now().strftime('%Y/%m/%d at %H:%M')})"

        all_lines: list[str] = []
        update_file = False
        if old_learning_path:
            # Current lines
            all_lines = learning_path.read_text().split("\n")
        else:
            # Load template
            with resources.as_file(
                resources.files(__name__.rsplit(".", maxsplit=1)[:-1][0] + ".templates")
                / "py-sandbox.template"
            ) as resource_path:
                all_lines = resource_path.read_text().split("\n")

        # Insert new rules in the file
        pattern: str
        if not DEBUG:
            pattern = r"^# </([^\}]+)>"
        else:
            pattern = r"^<!IGNORE!>"
        for i, line in enumerate(all_lines):
            match = re.search(pattern, line)
            if match and match.group(1) in replaces:
                if replaces[match.group(1)]:
                    logger.debug("Insert %s", match.group(1))
                    all_lines[i] = (
                        header + "\n" + replaces[match.group(1)] + "\n\n" + line
                    )
                    update_file = True
                    del replaces[match.group(1)]

        # If it's impossible to insert in the file, add rules at the end
        if replaces and any(replaces.values()):
            all_lines.append(header)
            for v in replaces.values():
                if v:
                    all_lines.append(v + "\n")
                    update_file = True
        if list(filter(lambda line: line.startswith("learn"), all_lines)):
            find_learning = " Remove the 'learn' parameter to use the sandboxes. "
        else:
            find_learning = ""

        if update_file:
            # Force level info
            old_level = pysandboxes_logger.level
            pysandboxes_logger.setLevel(logging.INFO)
            logger.debug(f"{learning_path=} {old_learning_path=}")
            if learning_path.absolute().is_relative_to(Path().absolute()):
                relative_lerning_path = learning_path.absolute().relative_to(
                    Path().absolute()
                )
            else:
                relative_lerning_path = learning_path
            msg = f"\nWrite all learning rules in '{relative_lerning_path}'. {find_learning}"
            if old_learning_path:
                msg += f"\nThe old version is here '{old_learning_path}'. "
                learning_path.rename(old_learning_path)

            msg += "\nCheck and update this file to validate the rules."
            pysandboxes_logger.info(msg)
            pysandboxes_logger.setLevel(old_level)
            learning_path.write_text("\n".join(all_lines))
        _save_learning_done = True


def _manage_olds_file(learning_path: Path) -> tuple[Path, Path | None]:
    """Manage backup files for configuration updates.

    Args:
        _learning_path: Path to the learning configuration file.

    Returns:
        Tuple of (current_path, backup_path).
    """
    old_learning_path = None

    if learning_path.exists() and not learning_path.is_dir():
        i = 0
        while True:
            suffix = f".old_{i}" if i else ".old"
            backup = learning_path.with_suffix(suffix)
            if not backup.exists():
                break
            i += 1
        old_learning_path = Path(backup)
    return learning_path, old_learning_path


def set_learning_path(learning_path: Path) -> None:
    """Activate learning mode for the specified configuration file.

    Args:
        learning_path: Path where learning rules should be saved.
    """
    global _learning_path
    _learning_path = learning_path


def is_learning_mode() -> bool:
    """Check if learning mode is currently active.

    Returns:
        True if learning mode is active, False otherwise.
    """
    global _learning_mode
    return _learning_mode


def set_learning_mode(mode: bool) -> None:
    global _learning_mode
    _learning_mode = mode


def add_learning_rule(rule: Any) -> None:
    """Add a rule to the learning set.

    Args:
        rule: The rule to add to the learning collection.
    """

    with _lock:

        if is_learning_mode() and rule not in _learning:
            _learning.add(rule)
            pysandboxes_logger.debug(repr(rule))
