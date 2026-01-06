import shutil

import os

import pytest
import fileinput

from pysandboxes.guard_files import activate_guard_files
from .test_guard_io import files


@pytest.fixture(autouse=True)
def reset_rules():
    from pysandboxes.guard_files import _deactivate_guard_files

    yield
    print("desactivate")  # FIXME
    _deactivate_guard_files()


def test_fileinput_input(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    activate_guard_files(rules)

    shutil.copy2(files["visible"],files["new_replace"])
    with fileinput.input(files=[files["new_replace"]],inplace=True,backup=".bak") as f:
        for line in f:
            print(line.replace("Visible", "in place"), end="")
    with open(files["new_replace"]) as f:
        assert f.read() == "in place"
    files["new_replace"].unlink()

