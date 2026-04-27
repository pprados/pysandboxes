from pathlib import Path

from pysandboxes.guard_files import _apply_dest_to_src_rules, _apply_src_to_dest_rules
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import activate_guard_files_rules


def test_apply_dest_to_src_rule() -> None:
    # TODO: test all paths, including path=""

    cwd = str(Path.cwd())
    src_dir = f"{cwd}/tests"
    dst_dir = f"{cwd}/pysandboxes"
    rules = [
        ConfigLine(f"bind={cwd},{cwd}", Path(), 0),
        ConfigLine(f"bind={src_dir},{dst_dir}", Path(), 0),
        ConfigLine("ignore=c*", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    assert _apply_dest_to_src_rules(f"{cwd}/a.txt", write=False, accept_dest=False) == (
        f"{cwd}/a.txt",
        None,
    ), "Accept a file with a bind rule"

    assert _apply_dest_to_src_rules(
        f"{src_dir}/a.txt", accept_src=True, write=False
    ) == (f"{dst_dir}/a.txt", None), "Accept a file with a bind rule with alias"

    error_result = _apply_dest_to_src_rules(
        f"{src_dir}/a.txt", accept_src=False, write=False
    )
    assert error_result[0] is None, "Ignore must detected"
    assert error_result[1] is not None, "Ignore must detected"

    ignore_result = _apply_dest_to_src_rules("c.txt", write=False)
    assert ignore_result[0] is None, "Ignore must detected"
    assert ignore_result[1] is not None, "Ignore must detected"

    # Test with directories
    assert _apply_dest_to_src_rules(f"{cwd}", write=False) == (
        f"{cwd}",
        None,
    ), "Accept a directory with a bind rule"
    assert _apply_dest_to_src_rules(f"{cwd}/", write=False) == (
        f"{cwd}/",
        None,
    ), "Accept a directory/ with a bind rule"
    assert _apply_dest_to_src_rules(f"{src_dir}", accept_src=True, write=False) == (
        f"{dst_dir}",
        None,
    ), "Accept a directory with a bind rule and alias"
    assert _apply_dest_to_src_rules(f"{src_dir}/", accept_src=True, write=False) == (
        f"{dst_dir}/",
        None,
    ), "Accept a directory/ with a bind rule and alias"

    assert _apply_dest_to_src_rules("/refuse.txt", write=False) == (
        None,
        None,
    ), "Refuse find without rules"

    assert _apply_dest_to_src_rules("", write=False) == (
        None,
        None,
    ), "Refuse empty filename"


def test_apply_src_to_dest_rules() -> None:
    cwd = str(Path.cwd())
    src_dir = f"{cwd}/tests"
    dst_dir = f"{cwd}/pysandboxes"
    rules = [
        ConfigLine(f"bind={cwd},{cwd}", Path(), 0),
        ConfigLine(f"bind={src_dir},{dst_dir}", Path(), 0),
        ConfigLine("ignore=c*", Path(), 0),
    ]
    activate_guard_files_rules(rules)

    # Test with file
    assert _apply_src_to_dest_rules(f"{cwd}/a.txt", accept_dest=False) == (
        f"{cwd}/a.txt",
        None,
    )

    assert _apply_src_to_dest_rules(f"{src_dir}/a.txt", accept_dest=False) == (
        f"{dst_dir}/a.txt",
        None,
    )
    refuse_error = _apply_src_to_dest_rules(f"{dst_dir}/a.txt", accept_dest=False)
    assert refuse_error[0] is None
    assert refuse_error[1] is not None

    assert _apply_src_to_dest_rules(f"{dst_dir}/a.txt", accept_dest=True) == (
        f"{dst_dir}/a.txt",
        None,
    )

    # Test with directories
    assert _apply_src_to_dest_rules(f"{cwd}", accept_dest=False) == (f"{cwd}", None)
    assert _apply_src_to_dest_rules(f"{cwd}/", accept_dest=False) == (f"{cwd}/", None)
    assert _apply_src_to_dest_rules(
        f"{src_dir}", accept_src=True, accept_dest=False
    ) == (f"{dst_dir}", None)

    refuse_error = _apply_src_to_dest_rules(f"{dst_dir}/", accept_dest=False)
    assert refuse_error[0] is None
    assert refuse_error[1] is not None

    assert _apply_src_to_dest_rules(f"{dst_dir}/", accept_dest=True) == (
        f"{dst_dir}",
        None,
    )
