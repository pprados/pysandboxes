import logging
import re
from datetime import datetime
from importlib import resources
from multiprocessing import Lock
from pathlib import Path
from typing import Any, List, Optional

from .main_logger import pysandboxes_logger

logger = logging.getLogger(__name__)

_lock = Lock()
_learning = set()

_learning_path: Optional[Path] = None


def generate_config_from_learning() -> None:
    global _learning_path
    from .guard_envs import generate_rules as env_generate_rules
    from .guard_files import generate_rules as file_generate_rules
    from .guard_import import generate_rules as import_generate_rules
    from .guard_socket import generate_rules as socket_generate_rules

    # Manage old files
    learning_path, old_learning_path = _manage_olds_file(_learning_path)

    # Manage envs rules
    env_rules = env_generate_rules()
    if env_rules:
        all_env_rules = "\n".join(env_rules)
    else:
        all_env_rules = None

    # Manage import rules
    import_rules = import_generate_rules(_learning)
    if import_rules:
        all_import_rules = "\n".join(import_rules)
    else:
        all_import_rules = None

    # Manage files rules
    file_rules = file_generate_rules(_learning)
    if file_rules:
        all_file_rules = "\n".join(file_rules)
    else:
        all_file_rules = None

    # Manage sockets rules
    socket_rules = socket_generate_rules(_learning)
    if socket_rules:
        all_socket_rules = "\n".join(socket_rules)
    else:
        all_socket_rules = None

    replaces = {
        # "learning_repeat": f"learn={learning_path}",
        "learning_guard_envs": all_env_rules,
        "learning_guard_import": all_import_rules,
        "learning_guard_files": all_file_rules,
        "learning_guard_socket": all_socket_rules,
    }

    header = f"# Add rules ({datetime.now().strftime('%d/%m/%y at %H:%M')})"

    all_lines: List[str] = []
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
    pattern: str = (
        r"^# XX</([^\}]+)>"  # FIX_RELEASE: XX pour forcer à la fin du fichier
    )
    for i, line in enumerate(all_lines):
        match = re.search(pattern, line)
        if match and match.group(1) in replaces:
            if replaces[match.group(1)]:
                logger.debug("Insert %s", match.group(1))
                all_lines[i] = header + "\n" + replaces[match.group(1)] + "\n\n" + line
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
        msg = "\nWrite all learning rules in '%s'. %s" % (
            learning_path.relative_to(Path()),
            find_learning,
        )
        if old_learning_path:
            msg += "The old version is here '%s'. " % (old_learning_path,)
            learning_path.rename(old_learning_path)

        msg += "Check and update this file to validate the rules."
        pysandboxes_logger.info(msg)
        pysandboxes_logger.setLevel(old_level)
        learning_path.write_text("\n".join(all_lines))


def _manage_olds_file(_learning_path):
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
        old_learning_path = backup
    return learning_path, old_learning_path


def activate_learning(config_file: Path) -> None:
    global _learning_path
    _learning_path = config_file


def stop_learning_mode():
    global _learning_path
    _learning_path = None


def is_learning_mode():
    global _learning_path
    return _learning_path is not None


def add_learning_rule(rule: Any) -> None:
    with _lock:
        _learning.add(rule)
        pysandboxes_logger.debug(repr(rule))
