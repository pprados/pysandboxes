import logging
import re
from datetime import datetime
from importlib import resources
from multiprocessing import Lock
from pathlib import Path
from typing import Any, Optional

from .main_logger import pysandboxes_logger

logger = logging.getLogger(__name__)

_lock = Lock()
_learning = []

_learning_path: Optional[Path] = None


def generate_config_from_learning() -> None:
    global _learning_path
    from .guard_files import generate_rules as file_generate_rules
    from .guard_socket import generate_rules as socket_generate_rules

    pysandboxes_logger.info("Generate config from learning")
    old_learning_path = None
    learning_path = _learning_path
    if learning_path.exists():
        i = 0
        while True:
            suffix = f".old_{i}" if i else ".old"
            backup = learning_path.with_suffix(suffix)
            if not backup.exists():
                break
            i += 1
        old_learning_path = backup

    file_rules = file_generate_rules(_learning)
    if file_rules:
        all_file_rules = (
            "\n".join(file_rules)
        )
    else:
        all_file_rules = None
    socket_rules = socket_generate_rules(_learning)
    if socket_rules:
        all_socket_rules = (
            "\n".join(socket_rules)
        )
    else:
        all_socket_rules = None

    replaces = {
        "learning_guard_files": all_file_rules,
        "learning_guard_socket": all_socket_rules,
    }

    if old_learning_path:
        # Add at the bottom
        all_lines = learning_path.read_text().split("\n")
        all_lines.append(
            f"\n# Add rules ({datetime.now().strftime('%d/%m/%y at %H:%M')})"
        )
        add_new_lines = False
        for v in replaces.values():
            if v:
                all_lines.append(v)
                add_new_lines = True
        if add_new_lines:
            pysandboxes_logger.warning("'%s' already exists. It's renamed to '%s'.",
                                       learning_path, old_learning_path)
            learning_path.rename(old_learning_path)
        else:
            # No modification
            return
    else:
        # Load template
        with resources.as_file(
                resources.files(
                    __name__.rsplit('.', maxsplit=1)[:-1][
                        0] + '.templates') / 'py-sandbox.template'
        ) as resource_path:
            all_lines = resource_path.read_text().split('\n')

        pattern: str = r'\{([^\}]+)\}'
        for i, line in enumerate(all_lines):
            match = re.search(pattern, line)
            if match and match.group(1) in replaces:
                if replaces[match.group(1)]:
                    all_lines[i] = replaces[match.group(1)]
                else:
                    all_lines[i] = ""
    learning_path.write_text(
        "\n".join(all_lines)
    )


def start_learning_mode(config_file: Path) -> None:
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
        _learning.append(rule)
        pysandboxes_logger.info(repr(rule))
