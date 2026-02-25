"""Learning mode implementation for automatic rule generation.

This module implements the learning mode functionality that observes sandbox
behavior and automatically generates security rules based on observed file access,
network connections, imports, and environment variable usage.

Learning mode helps developers bootstrap sandbox configurations by running their
application through typical usage scenarios and capturing required permissions.
"""

import logging
import re
from datetime import datetime
from importlib import resources
from multiprocessing import Lock
from pathlib import Path
from typing import Any, Set

from .config import CONFIG_NAME
from .main_logger import pysandboxes_logger, make_relative_path

logger = logging.getLogger(__name__)

_lock = Lock()
_learning: Set[Any] = set()

_learning_path: Path | None = None

# Check double usage
_lock_generate = Lock()
_save_learning_done: bool = False


def generate_config_from_learning() -> None:
    """Generate configuration file from observed learning rules.

    This function consolidates all rules collected during learning mode and
    writes them to a configuration file. It handles rule formatting, template
    processing, and file backup operations.
    """
    global _learning_path, _save_learning_done, _lock
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
        learning_path = _learning_path or Path(CONFIG_NAME)
        learning_path, old_learning_path = _manage_olds_file(learning_path)
        logger.debug(
            "generate_config_from_learning(%s,%s)",
            make_relative_path(learning_path),
            make_relative_path(old_learning_path)
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

        header = f"# Add rules ({datetime.now().strftime('%d/%m/%y at %H:%M')})"

        all_lines: list[str] = []
        update_file = False
        if old_learning_path:
            # Current lines
            all_lines = learning_path.read_text().split("\n")
        else:
            # Load template
            with resources.as_file(
                    resources.files(
                        __name__.rsplit(".", maxsplit=1)[:-1][0] + ".templates")
                    / "py-sandbox.template"
            ) as resource_path:
                all_lines = resource_path.read_text().split("\n")

        # Insert new rules in the file
        pattern: str = r"^# XX</([^\}]+)>"  # FIXME
        for i, line in enumerate(all_lines):
            match = re.search(pattern, line)
            if match and match.group(1) in replaces:
                if replaces[match.group(1)]:
                    logger.debug("Insert %s", match.group(1))
                    all_lines[i] = header + "\n" + replaces[
                        match.group(1)] + "\n\n" + line
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
            msg = "\nWrite all learning rules in '%s'. %s" % (
                learning_path.absolute().relative_to(Path().absolute()),
                find_learning,
            )
            if old_learning_path:
                msg += "The old version is here '%s'. " % (old_learning_path,)
                learning_path.rename(old_learning_path)

            msg += "Check and update this file to validate the rules."
            pysandboxes_logger.info(msg)
            pysandboxes_logger.setLevel(old_level)
            learning_path.write_text("\n".join(all_lines))
        _save_learning_done = True


def _manage_olds_file(_learning_path: Path) -> tuple[Path, Path | None]:
    """Manage backup files for configuration updates.

    Args:
        _learning_path: Path to the learning configuration file.

    Returns:
        Tuple of (current_path, backup_path).
    """
    old_learning_path = None
    learning_path = _learning_path
    if learning_path.exists() and not learning_path.is_dir():
        i = 0
        while True:
            suffix = f".old_{i}" if i else ".old"
            backup = learning_path.with_suffix(suffix)
            if not backup.exists():
                break
            i += 1
        old_learning_path = Path(backup)
    return Path(learning_path), old_learning_path


def activate_learning(config_file: Path) -> None:
    """Activate learning mode for the specified configuration file.

    Args:
        config_file: Path where learning rules should be saved.
    """
    global _learning_path
    _learning_path = config_file


def stop_learning_mode() -> None:
    """Deactivate learning mode."""
    global _learning_path
    _learning_path = None


def is_learning_mode() -> bool:
    """Check if learning mode is currently active.

    Returns:
        True if learning mode is active, False otherwise.
    """
    global _learning_path
    return _learning_path is not None


def add_learning_rule(rule: Any) -> None:
    """Add a rule to the learning set.

    Args:
        rule: The rule to add to the learning collection.
    """
    with _lock:
        if is_learning_mode():
            _learning.add(rule)
            pysandboxes_logger.debug(repr(rule))
