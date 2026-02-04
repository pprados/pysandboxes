import gzip

import pytest

from pysandboxes.types import ConfigLine
from .test_guard_io import files, _activate_guard


@pytest.fixture(autouse=True)
def reset_rules():
    from pysandboxes.guard_import import conv_patch_rules, _deactivate_guard_import, \
        activate_guard_import
    from pysandboxes.guard_files import _deactivate_guard_files, patch_rules
    activate_guard_import(
        conv_patch_rules(
            {
                **patch_rules(),
            }
        ),
        tuple(["*"]),  # Import all modules
    )
    yield
    _deactivate_guard_files()
    _deactivate_guard_import()


def test_gzip(files):
    from pathlib import Path

    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"--bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]

    _activate_guard(rules)

    import gzip
    import io
    from pathlib import Path

    source = files["bound_file"]
    compressed = files["bound_file"].with_suffix(".gz")
    with (source.open("rb") as f_in,
          gzip.open(compressed, "wb") as f_out):
        f_out.writelines(f_in)
    compressed.unlink()

    # FIXME: add les ignores tests
