from pathlib import Path
from typing import Dict

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleFileNotFoundError
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import (
    activate_guard_files_rules,
    files,  # noqa: F401
)


def test_builtins_open(files: Dict[str, Path]) -> None:  # noqa:F811
    from pathlib import Path

    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]

    activate_guard_files_rules(rules)

    import builtins

    with builtins.open(files["bind_dest"] / "bound_file.txt"):
        pass

    with pytest.raises(RuleFileNotFoundError):
        builtins.open(files["ignore"])
