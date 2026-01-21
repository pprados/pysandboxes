import logging
from pathlib import Path
from typing import Sequence, Tuple

from pysandboxes.types import ConfigLine

pysandboxes_logger = logging.getLogger("pysandbox")

ErrorMsg = Tuple[str, Path, int]


def format_ruleref(rule: ConfigLine) -> str:
    if rule.path == "":
        return ""
    elif rule.ln == 0:
        return rule.path
    else:
        return f"{rule.path}({rule.ln})"


def format_error_list(errors: Sequence[str]) -> str:
    return (
        errors[0] if len(errors) == 1
        else ', '.join(errors[:-1]) + " and " + errors[-1]
    )
