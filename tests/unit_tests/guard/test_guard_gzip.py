from pathlib import Path
from typing import Dict

import pytest

from pysandboxes import RuleFileNotFoundError
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import (
    activate_guard_files_rules,
    files,  # noqa: F401
)


def test_gzip(files: Dict[str, Path]) -> None:  # noqa: F811
    from pathlib import Path

    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"bind={files['path']},{files['path']}", Path(), 0),
        ConfigLine(f"bind={files['bind_src']},{files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    from pysandboxes.guard_files import _rules

    assert _rules

    import builtins
    import gzip
    import pathlib

    # FIXME: python version assert pathlib._local.io.open.__pysandbox__, "Sandbox not applied"
    assert builtins.open.__pysandbox__, "Sandbox not applied"  # type: ignore[attr-defined]

    source = pathlib.Path(files["bind_dest"] / "bound_file.txt")
    compressed = source.with_suffix(".gz")
    with source.open("rb") as f_in, gzip.open(compressed, "wb") as f_out:
        f_out.writelines(f_in)
    compressed.unlink()

    with pytest.raises(RuleFileNotFoundError):
        source = pathlib.Path(files["bind_dest"] / "bound_file.txt")
        compressed = pathlib.Path(files["bind_src"] / "bound_file.txt").with_suffix(
            ".gz"
        )
        with source.open("rb"), gzip.open(compressed, "wb"):
            pass
