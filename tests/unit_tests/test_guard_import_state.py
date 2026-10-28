# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
import sys

from hypothesis import given
from hypothesis import strategies as st

from pysandboxes import guard_import
from pysandboxes.guard_import import _activate_patch_import, _deactivate_guard_import
from pysandboxes.immutable_dict import ImmutableDict


def _consistent() -> bool:
    on_path = guard_import._guard_finder in sys.meta_path
    return guard_import._activated == on_path and (not on_path or sys.meta_path[0] is guard_import._guard_finder)


@given(st.lists(st.sampled_from(["activate", "deactivate"]), max_size=10))
def test_the_activated_flag_always_matches_the_finder_on_the_meta_path(ops: list[str]) -> None:
    assert _consistent()
    for op in ops:
        if op == "activate":
            was_active = guard_import._activated
            assert _activate_patch_import(ImmutableDict({})) is (not was_active)
            assert guard_import._activated
        else:
            _deactivate_guard_import()
            assert not guard_import._activated
            assert guard_import._guard_finder not in sys.meta_path
        assert _consistent()


def test_the_consistency_check_has_teeth() -> None:
    """Negative control: a flag left set after the finder is gone is reported."""
    saved = guard_import._activated
    try:
        _deactivate_guard_import()
        guard_import._activated = True
        assert not _consistent()
    finally:
        guard_import._activated = saved
