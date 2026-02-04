import pytest

from pysandboxes.guard_files import RuleFileNotFoundError
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


def test_builtins_open(files):
    from pathlib import Path

    rules = [
        ConfigLine(f"--ignore=*.log",Path(),0),
        ConfigLine(f"--bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"--bind={files['bind_src']},{files['bind_dest']}",Path(),0),
    ]

    _activate_guard(rules)

    import builtins

    with builtins.open(files['bind_dest'] / "bound_file.txt"):
        pass


    with pytest.raises(RuleFileNotFoundError):
        builtins.open(files['ignore'])

    with pytest.raises(RuleFileNotFoundError):
        builtins.open(files['bind_src'] / "bound_file.txt")
