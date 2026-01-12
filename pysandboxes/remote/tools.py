import base64
import contextvars
import logging
import os
import pickle
import shutil
import sys
from pathlib import Path
from typing import Any

_is_in_sandbox=False

_sandboxed=contextvars.ContextVar(
    'sanboxed', default=False)

def is_in_sandbox():
    return _sandboxed.get()

def set_is_in_sandbox(value: bool):
    _sandboxed.set(value)

def _to_b85(obj: Any) -> str:
    return base64.b85encode(
        pickle.dumps(obj,
                     protocol=pickle.HIGHEST_PROTOCOL
                     )).decode("utf-8")


def _from_b85(b85: str) -> Any:
    return pickle.loads(
        base64.b85decode(b85.encode("utf-8")),
    )

known_paths = [
    Path("/bin/"),
    Path("/usr/bin/"),
    Path("/usr/local/bin/"),
]

def which_command(command: Path) -> Path:

    for path in known_paths:
        if (path / command).exists():
            return path / command
    full_path=shutil.which(command)
    if not full_path:
        raise FileNotFoundError(f"Command {command} not found")
    return Path(full_path)

def get_venv() -> str | None:
    """
    Détecte le répertoire de l'environnement virtuel en comparant sys.prefix et sys.base_prefix.
    """
    if sys.prefix != sys.base_prefix:
        venv_path = sys.prefix
        return venv_path
    else:
        return os.environ.get('VIRTUAL_ENV')


def configure_logging_level(verbose_count: int) -> None:
    """
    Configures the logging level based on the number of verbose flags.

    Args:
        verbose_count (int): The number of '-v' flags provided by the user.
                             - 0: WARNING
                             - 1: INFO
                             - 2: DEBUG
                             - 3+: NOTSET (all messages, including custom trace levels if defined)
    """
    if verbose_count == 0:
        log_level = logging.WARNING
    elif verbose_count == 1:
        log_level = logging.INFO
    elif verbose_count == 2:
        log_level = logging.DEBUG
    else:  # verbose_count >= 3
        # NOTSET will log all messages, allowing custom levels below DEBUG if implemented
        log_level = logging.NOTSET

    logging.getLogger().setLevel(log_level)
