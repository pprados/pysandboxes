# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Which lines scripts/mutation.py leaves alone, and how it reads the known equivalents."""

import datetime
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

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


@pytest.fixture
def status(mutation: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A status file and a module tree of their own, with the commit of the run faked."""
    (tmp_path / "pysandboxes").mkdir()
    (tmp_path / "pysandboxes" / "a.py").write_text("A = 1\n")
    (tmp_path / "pysandboxes" / "b.py").write_text("B = 1\n")
    path = tmp_path / "status.json"
    monkeypatch.setattr(mutation, "ROOT", tmp_path)
    monkeypatch.setattr(mutation, "STATUS", path)
    monkeypatch.setattr(mutation.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="abc1234-dirty\n"))
    return path


def test_a_run_is_recorded_with_its_counts_its_commit_and_the_digest_of_the_module(
    mutation: ModuleType, status: Path
) -> None:
    mutation.record_status("pysandboxes/a.py", {"killed": 7, "survived": 1})

    entry = json.loads(status.read_text())["pysandboxes/a.py"]
    assert entry == {
        "date": datetime.date.today().isoformat(),
        "commit": "abc1234-dirty",
        "source": mutation.source_digest("pysandboxes/a.py"),
        "killed": 7,
        "survived": 1,
    }


def test_a_new_run_replaces_the_entry_of_its_module_and_keeps_the_others(mutation: ModuleType, status: Path) -> None:
    mutation.record_status("pysandboxes/a.py", {"killed": 7, "survived": 1})
    mutation.record_status("pysandboxes/b.py", {"killed": 2})

    mutation.record_status("pysandboxes/a.py", {"killed": 9})

    recorded = json.loads(status.read_text())
    assert sorted(recorded) == ["pysandboxes/a.py", "pysandboxes/b.py"]
    assert recorded["pysandboxes/a.py"]["killed"] == 9
    assert "survived" not in recorded["pysandboxes/a.py"]


def test_the_digest_follows_the_content_of_the_module(mutation: ModuleType, status: Path) -> None:
    before = mutation.source_digest("pysandboxes/a.py")

    (mutation.ROOT / "pysandboxes" / "a.py").write_text("A = 2\n")

    assert mutation.source_digest("pysandboxes/a.py") != before
    assert len(before) == 12


def test_the_report_tells_which_modules_changed_since_their_run(mutation: ModuleType, status: Path) -> None:
    mutation.record_status("pysandboxes/a.py", {"killed": 7, "survived": 1, "equivalent": 2, "skipped": 30})
    mutation.record_status("pysandboxes/b.py", {"killed": 2})
    (mutation.ROOT / "pysandboxes" / "b.py").write_text("B = 2\n")

    header, first, second = mutation.status_report()

    assert header.split() == ["module", "date", "commit", "killed", "surv.", "equiv.", "noexec", "state"]
    assert first.split()[0] == "pysandboxes/a.py"
    assert first.split()[3:7] == ["7", "1", "2", "30"]
    assert first.endswith("code unchanged")
    assert second.endswith("code changed since")


def test_the_report_flags_a_module_that_no_longer_exists_and_shows_the_note(mutation: ModuleType, status: Path) -> None:
    mutation.record_status("pysandboxes/a.py", {"killed": 7})
    recorded = json.loads(status.read_text())
    recorded["pysandboxes/a.py"]["note"] = "fixed afterwards"
    status.write_text(json.dumps(recorded))
    (mutation.ROOT / "pysandboxes" / "a.py").unlink()

    _, line = mutation.status_report()

    assert line.endswith("module gone (fixed afterwards)")


def test_the_report_of_an_empty_status_is_only_the_header(mutation: ModuleType, status: Path) -> None:
    assert len(mutation.status_report()) == 1


def test_status_prints_the_report_without_running_anything(
    mutation: ModuleType, status: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    mutation.record_status("pysandboxes/a.py", {"killed": 7})
    monkeypatch.setattr(sys, "argv", ["mutation.py", "--status"])

    assert mutation.main() == 0

    assert "pysandboxes/a.py" in capsys.readouterr().out


def test_a_module_is_required_unless_status_is_asked(mutation: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["mutation.py"])

    with pytest.raises(SystemExit) as stop:
        mutation.main()

    assert stop.value.code == 2
