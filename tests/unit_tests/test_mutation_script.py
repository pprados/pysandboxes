# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Which lines scripts/mutation.py leaves alone, and how it reads the known equivalents."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).parents[2] / "scripts" / "mutation.py"
_SOURCE = '''\
def run(a, b):
    """Doc."""
    logger.info("start %s", a)
    if a == b:  # pragma: no mutate
        c = a < b
    d = a > b
    e = (
        a >= b  # pragma: no mutate
    )
    log.debug("end")
    return d, e
'''


@pytest.fixture(scope="module")
def mutation() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mutation_script", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_logging_calls_are_never_mutated(mutation: ModuleType) -> None:
    assert {3, 10} <= mutation.skipped_lines(_SOURCE)


def test_a_pragma_on_a_compound_statement_spares_its_header_only(mutation: ModuleType) -> None:
    skipped = mutation.skipped_lines(_SOURCE)

    assert 4 in skipped
    assert 5 not in skipped


def test_a_pragma_inside_a_multiline_statement_spares_the_whole_statement(mutation: ModuleType) -> None:
    assert {7, 8, 9} <= mutation.skipped_lines(_SOURCE)


def test_the_other_lines_stay_mutable(mutation: ModuleType, tmp_path: Path) -> None:
    module = tmp_path / "m.py"
    module.write_text(_SOURCE)

    assert mutation.body_lines(module) == {5, 6, 11}


def test_known_equivalents_skip_comments_and_blank_lines(
    mutation: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    listing = tmp_path / "eq.txt"
    listing.write_text("# why\n\npysandboxes/a.py | ReplaceComparisonOperator_Lt_LtE | if x < 3 | 4:\n")
    monkeypatch.setattr(mutation, "EQUIVALENTS", listing)

    assert mutation.known_equivalents() == {("pysandboxes/a.py", "ReplaceComparisonOperator_Lt_LtE", "if x < 3 | 4:")}
