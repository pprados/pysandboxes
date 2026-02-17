import pytest

from pysandboxes import RuleFileNotFoundError
from pysandboxes.sb_types import ConfigLine
from .test_guard_io import files, activate_guard_files_rules


def test_gzip(files):
    from pathlib import Path

    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
        # ConfigLine(f"bind=tests,tests", Path(), 0),
        # ConfigLine(f"bind=.venv,.venv", Path(), 0),
        # ConfigLine(f"bind=.pytest_cache,.pytest_cache", Path(), 0),
        # ConfigLine(f"bind=/tmp/pytest-of-philippe-prados/,/tmp/pytest-of-philippe-prados/", Path(), 0),
        # ConfigLine(f"bind='/home/philippe-prados/miniconda3,/home/philippe-prados/miniconda3", Path(), 0),
    ]
    # FIXME: nettoyer
    # from pysandboxes.py_sandbox import parse_config
    # from pysandboxes.py_sandbox import activate_sandboxes
    # all_rules=parse_config(rules,
    #              config_path=".",
    #              envs={},
    #              )
    # activate_sandboxes(all_rules,{})
    activate_guard_files_rules(rules)

    # FIXME: test pour debug
    from pysandboxes.guard_files import _rules
    assert _rules

    import gzip
    import pathlib
    import builtins

    assert pathlib._local.io.open.__pysandbox__, "Sandbox not applied"
    assert builtins.open.__pysandbox__, "Sandbox not applied"

    source = pathlib.Path(files["bind_dest"] / "bound_file.txt")
    compressed = source.with_suffix(".gz")
    with (source.open("rb") as f_in,
          gzip.open(compressed, "wb") as f_out):
        f_out.writelines(f_in)
    compressed.unlink()

    with pytest.raises(RuleFileNotFoundError):
        source = pathlib.Path(files["bind_dest"] / "bound_file.txt")
        compressed = pathlib.Path(files["bind_src"] / "bound_file.txt").with_suffix(
            ".gz")
        with (source.open("rb"),
              gzip.open(compressed, "wb")):
            pass
