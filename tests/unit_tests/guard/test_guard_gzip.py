import shutil

import os

import pytest
import gzip

from pysandboxes.guard_files import activate_guard_files
from .test_guard_io import files, str_activate_guard_files


@pytest.fixture(autouse=True)
def reset_rules():
    from pysandboxes.guard_files import _deactivate_guard_files

    yield
    print("desactivate")  # FIXME
    _deactivate_guard_files()


def test_gzip(files):
    rules = [
        f"--ignore=*.log",
        f"--bind={files['bind_src']},{files['bind_dest']}",
    ]

    str_activate_guard_files(rules)

    source = files["bound_file"]
    compressed = files["bound_file"].with_suffix(".gz")
    with (source.open("rb") as f_in,
          gzip.open(compressed, "wb") as f_out):
        f_out.writelines(f_in)
    compressed.unlink()
