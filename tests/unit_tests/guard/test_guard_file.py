import os
from pathlib import Path

from pysandboxes.guard_files import _apply_dest_to_src_rules, _apply_src_to_dest_rules
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import activate_guard_files_rules


def test_apply_dest_to_src_rule() -> None:
    cwd = str(Path.cwd())
    src_dir = f"{cwd}/tests"
    rules = [
        ConfigLine(f"expose-rw={cwd}", Path(), 0),
        ConfigLine("ignore=c*", Path(), 0),
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

    ignore_result = _apply_dest_to_src_rules("c.txt", write=False)
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


def test_apply_src_to_dest_rules() -> None:
    cwd = str(Path.cwd())
    src_dir = f"{cwd}/tests"
    dst_dir = f"{cwd}/pysandboxes"
    rules = [
        ConfigLine(f"expose-rw={cwd}", Path(), 0),
        ConfigLine("ignore=c*", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    assert _apply_src_to_dest_rules(f"{cwd}/a.txt") == (f"{cwd}/a.txt", None)
    assert _apply_src_to_dest_rules(f"{src_dir}/a.txt") == (f"{src_dir}/a.txt", None)
    assert _apply_src_to_dest_rules(f"{dst_dir}/a.txt") == (f"{dst_dir}/a.txt", None)

    ignore_result = _apply_src_to_dest_rules("c.txt")
    assert ignore_result[0] is None
    assert ignore_result[1] is not None

    assert _apply_src_to_dest_rules(f"{cwd}", accept_dest=False) == (f"{cwd}", None)
    assert _apply_src_to_dest_rules(f"{cwd}/", accept_dest=False) == (
        os.path.abspath(cwd),
        None,
    )
    assert _apply_src_to_dest_rules(
        f"{src_dir}", accept_src=True, accept_dest=False
    ) == (f"{src_dir}", None)

    assert _apply_src_to_dest_rules(f"{dst_dir}/", accept_dest=False) == (
        os.path.abspath(dst_dir),
        None,
    )

    refuse = _apply_src_to_dest_rules("/refuse.txt", accept_dest=False)
    assert refuse == ("/refuse.txt", None)
