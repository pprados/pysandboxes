import pytest

from pysandboxes import RuleFileNotFoundError
from pysandboxes.sb_types import ConfigLine
from .test_guard_io import files, _reset_rules, activate_guard_files_rules


def test_builtins_open(files):
    from pathlib import Path

    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]

    activate_guard_files_rules(rules)

    import builtins
    with builtins.open(files['bind_dest'] / "bound_file.txt"):
        pass

    with pytest.raises(RuleFileNotFoundError):
        builtins.open(files['ignore'])

    with pytest.raises(RuleFileNotFoundError):
        builtins.open(files['bind_src'] / "bound_file.txt")
