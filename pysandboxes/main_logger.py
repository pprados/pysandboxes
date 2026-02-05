import logging
from pathlib import Path
from typing import Sequence, Tuple

from .types import ConfigLine

pysandboxes_logger = logging.getLogger("Pysandboxes")

ErrorMsg = Tuple[str, Path, int]


def format_ruleref(rule: ConfigLine) -> str:
    if rule.path == Path():
        path = "<arg>"
    else:
        path = str(rule.path.absolute().relative_to(Path.cwd()))
    if rule.ln == 0:
        return path
    else:
        return f"{path}({rule.ln})"


def format_error_list(errors: Sequence[str]) -> str:
    return (
        errors[0] if len(errors) == 1
        else ', '.join(errors[:-1]) + " and " + errors[-1]
    )
