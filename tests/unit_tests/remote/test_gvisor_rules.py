# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What the rules expose to a gVisor guest, and what they hide inside it."""

import logging
import os
from pathlib import Path

import pytest

from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.remote.gvisor_bundle import exposures, mask_targets
from pysandboxes.sb_types import ConfigLine

_CONFIG = ConfigLine("rule", Path("profile"), 1)


def _expose(path: str | Path, *, write: bool = False) -> FSExposeRule:
    return FSExposeRule(path=str(path), write=write, config=_CONFIG)


def _ignore(pattern: str) -> IgnoreRule:
    return IgnoreRule(source=pattern, config=_CONFIG)


def _exposures(
    tmp_path: Path, *rules: FSExposeRule | IgnoreRule, runtime: list[str] | None = None
) -> tuple[list[str], list[str]]:
    all_rules = EmptyRules._replace(file_rules=tuple(rules))
    return exposures(all_rules, runtime_paths=runtime or [], guest_dir=str(tmp_path / "guest"))


def test_an_expose_ro_rule_is_exposed_read_only(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()

    ro, rw = _exposures(tmp_path, _expose(data))

    assert str(data) in ro
    assert str(data) not in rw


def test_a_rule_cannot_make_the_guest_config_directory_writable(tmp_path: Path) -> None:
    guest = tmp_path / "guest"
    guest.mkdir()

    ro, rw = _exposures(tmp_path, _expose(guest, write=True))

    assert str(guest) in ro
    assert str(guest) not in rw


def test_an_expose_rw_rule_is_exposed_read_write(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    ro, rw = _exposures(tmp_path, _expose(scratch, write=True))

    assert str(scratch) in rw
    assert str(scratch) not in ro


def test_the_trailing_separator_of_a_directory_rule_is_dropped(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()

    ro, _ = _exposures(tmp_path, _expose(f"{data}/"))

    assert str(data) in ro
    assert f"{data}/" not in ro


def test_a_path_missing_on_the_host_is_not_exposed(tmp_path: Path) -> None:
    ro, rw = _exposures(tmp_path, _expose(tmp_path / "absent"), _expose(tmp_path / "gone", write=True))

    assert not any("absent" in p or "gone" in p for p in ro + rw), (
        "runsc refuses to start on a bind of a missing source"
    )


def test_a_device_is_not_exposed_and_the_rule_is_reported(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        ro, rw = _exposures(tmp_path, _expose("/dev/null"))

    assert "/dev/null" not in ro + rw
    assert "/dev/null" in caplog.text, "a rule the guest cannot honour is reported, not silently dropped"


@pytest.mark.parametrize("path", ["/dev", "/dev/", "/proc", "/proc/", "/proc/self", "/proc/sys"])
def test_the_host_dev_and_proc_are_never_bound_into_the_guest(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, path: str
) -> None:
    with caplog.at_level(logging.WARNING):
        ro, rw = _exposures(tmp_path, _expose(path), _expose(path, write=True))

    assert not any(p.rstrip("/") == path.rstrip("/") for p in ro + rw), "the guest has a /dev and a /proc of its own"
    assert path.rstrip("/") in caplog.text


def test_the_interpreter_paths_are_exposed_read_only(tmp_path: Path) -> None:
    runtime = tmp_path / "venv"
    runtime.mkdir()

    ro, _ = _exposures(tmp_path, runtime=[str(runtime)])

    assert str(runtime) in ro


def test_nothing_is_writable_without_a_rule(tmp_path: Path) -> None:
    _, rw = _exposures(tmp_path)

    assert rw == []


def test_the_guest_config_directory_is_read_only_and_the_run_directory_is_not_exposed(tmp_path: Path) -> None:
    ro, rw = _exposures(tmp_path)

    assert str(tmp_path / "guest") in ro
    assert str(tmp_path / "guest") not in rw
    assert str(tmp_path) not in ro + rw, "the run directory holds the spec, the filter and the config pipe"


def test_the_system_directories_are_exposed_read_only(tmp_path: Path) -> None:
    ro, _ = _exposures(tmp_path)

    assert "/usr" in ro
    assert "/etc" in ro


def test_an_ignored_file_inside_an_exposed_directory_is_masked(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET")

    masks = mask_targets(_ignore_rules(".env"), str(tmp_path), [str(tmp_path)])

    assert masks == [(str(tmp_path / ".env"), False)]


def test_an_ignored_directory_is_masked_as_a_directory(tmp_path: Path) -> None:
    (tmp_path / "secrets").mkdir()

    masks = mask_targets(_ignore_rules("secrets"), str(tmp_path), [str(tmp_path)])

    assert masks == [(str(tmp_path / "secrets"), True)]


def test_an_ignored_file_outside_every_exposure_needs_no_mask(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET")

    assert mask_targets(_ignore_rules(".env"), str(tmp_path), []) == []


def test_an_ignored_file_in_a_directory_a_rule_exposes_is_masked_wherever_the_cwd_is(tmp_path: Path) -> None:
    exposed, elsewhere = tmp_path / "exposed", tmp_path / "elsewhere"
    exposed.mkdir()
    elsewhere.mkdir()
    (exposed / ".env").write_text("SECRET")
    rules = EmptyRules._replace(file_rules=(_expose(exposed), _ignore(".env")))

    masks = mask_targets(rules, str(elsewhere), [str(exposed)])

    assert masks == [(str(exposed / ".env"), False)], "the exposure names the directory; the cwd is not the only tree"


def test_a_directory_only_the_system_exposes_is_not_walked_for_ignore_rules(tmp_path: Path) -> None:
    system = tmp_path / "system"
    system.mkdir()
    (system / ".env").write_text("SECRET")

    assert mask_targets(_ignore_rules(".env"), str(tmp_path / "elsewhere"), [str(system)]) == []


def test_a_symlink_is_masked_through_the_file_it_points_to(tmp_path: Path) -> None:
    real = tmp_path / "real.txt"
    real.write_text("SECRET")
    os.symlink(real, tmp_path / ".env")

    masks = mask_targets(_ignore_rules(".env"), str(tmp_path), [str(tmp_path)])

    assert masks == [(str(real), False)], "runsc refuses a symlink as a mount destination"


def test_nothing_is_masked_without_an_ignore_rule(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET")

    assert mask_targets(EmptyRules, str(tmp_path), [str(tmp_path)]) == []


def _ignore_rules(pattern: str) -> AllRules:
    return EmptyRules._replace(file_rules=(_ignore(pattern),))
