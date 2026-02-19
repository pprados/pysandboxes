import fileinput
import shutil
from pathlib import Path
from typing import Dict

import pytest

from pysandboxes.sb_types import ConfigLine

from .test_guard_io import _reset_rules, activate_guard_files_rules, files


def test_fileinput_input(files:Dict[str,Path]) -> None:
    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]

    activate_guard_files_rules(rules)

    shutil.copy2(files["visible"], files["new_replace"])
    with fileinput.input(
        files=[files["new_replace"]], inplace=True, backup=".bak"
    ) as f:
        for line in f:
            print(line.replace("Visible", "in place"), end="")
    with open(files["new_replace"]) as f:
        assert f.read() == "in place"
    files["new_replace"].unlink()
