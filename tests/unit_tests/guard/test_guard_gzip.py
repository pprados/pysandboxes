from pathlib import Path
from typing import Dict

import pytest  # type: ignore[import-untyped]

from pysandboxes import RuleFileNotFoundError
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import (
    activate_guard_files_rules,
    files,  # noqa: F401
)


def test_gzip(files: Dict[str, Path]) -> None:  # FIXME noqa: F811
    from pathlib import Path

    rules = [
        ConfigLine("ignore=*.log", Path(), 0),
        ConfigLine(f"expose-rw={files['path']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_src']}", Path(), 0),
        ConfigLine(f"expose-rw={files['bind_dest']}", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    from pysandboxes.guard_files import _rules

    assert _rules

    import builtins
    import gzip
    import pathlib

    assert builtins.open.__pysandbox__, "Sandbox not applied"  # type: ignore[attr-defined]

    source = pathlib.Path(files["bind_dest"] / "bound_file.txt")
    compressed = source.with_suffix(".gz")
    with source.open("rb") as f_in, gzip.open(compressed, "wb") as f_out:
        f_out.writelines(f_in)
    compressed.unlink()

    out_gz = pathlib.Path(files["bind_dest"] / "roundtrip.gz")
    source = pathlib.Path(files["bind_src"] / "bound_file.txt")
    with source.open("rb") as f_in, gzip.open(out_gz, "wb") as f_out:
        f_out.writelines(f_in)
    out_gz.unlink()
