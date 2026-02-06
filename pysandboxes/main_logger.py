import logging
from pathlib import Path
from typing import Sequence, Tuple

from .sb_types import ConfigLine

pysandboxes_logger = logging.getLogger("Pysandboxes")

ErrorMsg = Tuple[str, Path, int]


def make_relative_path(path:Path) -> str:
    try:
        rel_path = str(path.absolute().relative_to(Path.cwd()))
    except ValueError:
        # File not relative to cwd
        try:
            path.absolute().relative_to(Path.home())
            rel_path = "~" + str(path.absolute())[len(str(Path.home())):]
        except ValueError:
            # File not in home
            rel_path = str(path.absolute())
    return rel_path

def format_ruleref(rule: ConfigLine) -> str:
    if rule.path == Path():
        path = "<arg>"
    else:
        path = make_relative_path(rule.path)
    if rule.ln == 0:
        return path
    else:
        return f"{path}({rule.ln})"


def format_error_list(errors: Sequence[str]) -> str:
    return (
        errors[0] if len(errors) == 1
        else ', '.join(errors[:-1]) + " and " + errors[-1]
    )
