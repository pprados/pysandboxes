# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2

from pathlib import Path

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.remote.libkrun_root import exposures, mask_targets
from pysandboxes.sb_types import ConfigLine

_LINE = ConfigLine("", Path(), 0)


def _rules(*file_rules):
    return EmptyRules._replace(file_rules=tuple(file_rules))


def test_a_directory_is_read_only_unless_a_rule_makes_it_writable(tmp_path: Path) -> None:
    read_only, read_write = tmp_path / "ro", tmp_path / "rw"
    read_only.mkdir()
    read_write.mkdir()
    rules = _rules(FSExposeRule(str(read_only), False, _LINE), FSExposeRule(str(read_write), True, _LINE))

    ro, rw = exposures(rules, runtime=[], run_dir="/nowhere")

    assert str(read_only) in ro and str(read_write) not in ro
    assert rw == [str(read_write)]


def test_the_system_and_the_runtime_are_exposed_read_only_without_any_rule(tmp_path: Path) -> None:
    ro, rw = exposures(_rules(), runtime=[str(tmp_path)], run_dir="/nowhere")

    assert "/usr" in ro and str(tmp_path) in ro
    assert rw == []


def test_a_path_named_both_ways_stays_read_only(tmp_path: Path) -> None:
    rules = _rules(FSExposeRule(str(tmp_path), True, _LINE))

    ro, rw = exposures(rules, runtime=[str(tmp_path)], run_dir="/nowhere")

    assert str(tmp_path) in ro and rw == []


def test_the_host_home_is_not_exposed_unless_a_rule_names_it(tmp_path: Path) -> None:
    ro, rw = exposures(_rules(), runtime=[], run_dir="/nowhere")

    assert str(Path.home()) not in ro + rw


def test_a_rule_on_dev_or_a_missing_path_is_left_out(tmp_path: Path) -> None:
    rules = _rules(FSExposeRule("/dev/null", False, _LINE), FSExposeRule(str(tmp_path / "absent"), True, _LINE))

    ro, rw = exposures(rules, runtime=[], run_dir="/nowhere")

    assert "/dev/null" not in ro and str(tmp_path / "absent") not in ro + rw


def test_the_run_directory_is_never_exposed_through_the_root(tmp_path: Path) -> None:
    ro, rw = exposures(_rules(FSExposeRule(str(tmp_path), True, _LINE)), runtime=[], run_dir=str(tmp_path))

    assert str(tmp_path) not in ro + rw


def test_an_ignore_rule_masks_a_match_inside_an_exposed_directory(tmp_path: Path) -> None:
    (tmp_path / "private.key").write_text("x")
    (tmp_path / "public.txt").write_text("y")
    rules = _rules(FSExposeRule(str(tmp_path), False, _LINE), IgnoreRule("private.key", _LINE))

    masks = mask_targets(rules, str(tmp_path), [str(tmp_path)])

    assert masks == [(str(tmp_path / "private.key"), False)]


def test_without_an_ignore_rule_nothing_is_masked(tmp_path: Path) -> None:
    assert mask_targets(_rules(FSExposeRule(str(tmp_path), False, _LINE)), str(tmp_path), [str(tmp_path)]) == []
