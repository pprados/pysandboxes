import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pysandboxes.guard_files import (
    LearnFileRule,
    _apply_dest_to_src_rules,
    _apply_src_to_dest_rules,
    generate_rules,
)
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import activate_guard_files_rules


@pytest.mark.skipif(sys.platform == "win32", reason="expected paths are POSIX literals")
def test_apply_dest_to_src_rule() -> None:
    # The ignore pattern must not match the name of the directory the suite
    # happens to run from: `ignore=c*` silently captured any checkout called
    # `cleanup`, `code`, ... and the assertions below expect the exposed
    # directory to come back untouched.
    cwd = str(Path.cwd())
    src_dir = f"{cwd}/tests"
    rules = [
        ConfigLine(f"expose-rw={cwd}", Path(), 0),
        ConfigLine("ignore=zz-ignored-*", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    assert _apply_dest_to_src_rules(f"{cwd}/a.txt", write=False) == (
        f"{cwd}/a.txt",
        None,
    )

    assert _apply_dest_to_src_rules(f"{src_dir}/a.txt", write=False) == (
        f"{src_dir}/a.txt",
        None,
    )

    ignore_result = _apply_dest_to_src_rules("zz-ignored-1.txt", write=False)
    assert ignore_result[0] is None
    assert ignore_result[1] is not None

    assert _apply_dest_to_src_rules(f"{cwd}", write=False) == (f"{cwd}", None)
    assert _apply_dest_to_src_rules(f"{cwd}/", write=False) == (f"{cwd}/", None)
    assert _apply_dest_to_src_rules(f"{src_dir}", write=False) == (
        f"{src_dir}",
        None,
    )
    assert _apply_dest_to_src_rules(f"{src_dir}/", write=False) == (
        f"{src_dir}/",
        None,
    )

    assert _apply_dest_to_src_rules("/refuse.txt", write=False) == (None, None)
    assert _apply_dest_to_src_rules("", write=False) == (None, None)


@pytest.mark.skipif(sys.platform == "win32", reason="expected paths are POSIX literals")
def test_apply_src_to_dest_rules() -> None:
    cwd = str(Path.cwd())
    src_dir = f"{cwd}/tests"
    dst_dir = f"{cwd}/pysandboxes"
    rules = [
        ConfigLine(f"expose-rw={cwd}", Path(), 0),
        ConfigLine("ignore=zz-ignored-*", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    assert _apply_src_to_dest_rules(f"{cwd}/a.txt") == (f"{cwd}/a.txt", None)
    assert _apply_src_to_dest_rules(f"{src_dir}/a.txt") == (f"{src_dir}/a.txt", None)
    assert _apply_src_to_dest_rules(f"{dst_dir}/a.txt") == (f"{dst_dir}/a.txt", None)

    ignore_result = _apply_src_to_dest_rules("zz-ignored-1.txt")
    assert ignore_result[0] is None
    assert ignore_result[1] is not None

    assert _apply_src_to_dest_rules(f"{cwd}") == (f"{cwd}", None)
    assert _apply_src_to_dest_rules(f"{cwd}/") == (
        os.path.abspath(cwd),
        None,
    )
    assert _apply_src_to_dest_rules(f"{src_dir}") == (f"{src_dir}", None)

    assert _apply_src_to_dest_rules(f"{dst_dir}/") == (
        os.path.abspath(dst_dir),
        None,
    )

    refuse = _apply_src_to_dest_rules("/refuse.txt")
    assert refuse == ("/refuse.txt", None)


def test_generate_rules_gives_a_temporary_directory_a_fallback(tmp_path: Path) -> None:
    # A learned rule naming a temporary directory must stay usable on a machine
    # that sets none of TMPDIR, TEMP or TMP -- a stock Linux shell, or a CI
    # runner. A bare ${TMPDIR} expands to nothing there and the whole config
    # file becomes a syntax error.
    work = tmp_path / "run" / "data"
    work.mkdir(parents=True)

    with patch.dict(
        "pysandboxes.guard_files._special_env",
        {"TMPDIR": str(tmp_path)},
        clear=True,
    ):
        rules = generate_rules({LearnFileRule(work, False)})

    assert "expose-ro=${TMPDIR:-/tmp}/run/data" in rules


def test_generate_rules_leaves_a_home_relative_path_alone(tmp_path: Path) -> None:
    # Only the temporary directory keys get a default: a default for a key
    # naming a machine-specific path would silently expose the learning
    # machine's directory rather than fail where a human can see it.
    work = tmp_path / "project"
    work.mkdir()

    with patch.dict(
        "pysandboxes.guard_files._special_env",
        {"HOME": str(tmp_path)},
        clear=True,
    ):
        rules = generate_rules({LearnFileRule(work, False)})

    assert "expose-ro=~/project" in rules
