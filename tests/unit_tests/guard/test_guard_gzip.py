import pytest

from pysandboxes.guard_files import RuleFileNotFoundError
from pysandboxes.types import ConfigLine
from .test_guard_io import files, _activate_guard, _reset_rules


@pytest.fixture(autouse=True)
def reset_rules():
    yield from _reset_rules()


def test_gzip(files):
    from pathlib import Path

    rules = [
        ConfigLine(f"ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]

    _activate_guard(rules)

    import gzip
    import pathlib

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
        with (source.open("rb") as f_in,
              gzip.open(compressed, "wb") as f_out):
            pass
