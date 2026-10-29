# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
import os

import pytest  # type: ignore[import-untyped]

from pysandboxes.guard_files import _rule_covers

SEP = os.sep


@pytest.mark.parametrize(
    "rule, path",
    [
        (f"{SEP}a{SEP}", f"{SEP}a"),
        (f"{SEP}a{SEP}", f"{SEP}a{SEP}"),
        (f"{SEP}a{SEP}", f"{SEP}a{SEP}b"),
        (f"{SEP}a{SEP}", f"{SEP}a{SEP}b{SEP}c"),
        (f"{SEP}a", f"{SEP}a"),
        (f"{SEP}a", f"{SEP}a{SEP}"),
    ],
)
def test_a_rule_covers_its_own_tree(rule: str, path: str) -> None:
    assert _rule_covers(rule, path)


@pytest.mark.parametrize(
    "rule, path",
    [
        (f"{SEP}a{SEP}", f"{SEP}ab"),
        (f"{SEP}a{SEP}", f"{SEP}a.txt"),
        (f"{SEP}a{SEP}", f"{SEP}b"),
        (f"{SEP}a{SEP}b{SEP}", f"{SEP}a"),
        (f"{SEP}a", f"{SEP}ab"),
        (f"{SEP}a", f"{SEP}a{SEP}b"),
    ],
)
def test_a_rule_does_not_cover_a_sibling_that_shares_its_prefix(rule: str, path: str) -> None:
    assert not _rule_covers(rule, path)
