# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A device is exposed as itself, never through its directory.

`/dev/null` is reachable without granting `/dev`: the few harmless devices are exposed as file rules without a
profile line, a learned device yields a file rule, and a file rule covers that file only.
"""

import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pysandboxes import guard_files
from pysandboxes.guard_files import FSExposeRule, generate_rules, parse_rules
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine

from .test_guard_io import _deactivate_all_rules, activate_guard_files_rules

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX device files")

NULL = "/dev/null"


def _implicit_device_rules() -> dict[str, bool]:
    errors: list[ErrorMsg] = []
    file_rules, _ = parse_rules([], errors)
    assert not errors
    return {r.path: r.write for r in file_rules if isinstance(r, FSExposeRule) and r.config.rule == "<safe-devices>"}


def test_the_harmless_devices_are_exposed_without_a_profile_line() -> None:
    rules = _implicit_device_rules()

    assert rules[NULL] is True
    assert rules["/dev/urandom"] is False
    assert "/dev" not in rules and "/dev/" not in rules


def test_a_device_that_can_reach_hardware_or_a_terminal_is_not_implicit() -> None:
    assert {"/dev/tty", "/dev/full", "/dev/mem", "/dev/kmsg"}.isdisjoint(_implicit_device_rules())


def test_a_missing_device_adds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard_files, "SAFE_DEVICES", (("/dev/does-not-exist", False),))

    assert _implicit_device_rules() == {}


def test_parse_rules_accepts_a_device_as_a_file_rule() -> None:
    errors: list[ErrorMsg] = []

    file_rules, _ = parse_rules([ConfigLine("expose-ro=/dev/zero", Path(), 0)], errors)

    assert not errors
    assert [r.path for r in file_rules if isinstance(r, FSExposeRule) and r.config.rule == "expose-ro=/dev/zero"] == [
        "/dev/zero"
    ]


def test_parse_rules_still_refuses_a_regular_file(tmp_path: Path) -> None:
    plain = tmp_path / "f.txt"
    plain.write_text("x")
    errors: list[ErrorMsg] = []

    parse_rules([ConfigLine(f"expose-ro={plain}", Path(), 0)], errors)

    assert len(errors) == 1 and "must be a directory" in errors[0][0]


def test_the_null_device_opens_without_any_rule_on_dev() -> None:
    activate_guard_files_rules([])
    try:
        with open(NULL, "w") as sink:
            sink.write("x")
        with open("/dev/urandom", "rb") as source:
            assert len(source.read(4)) == 4
    finally:
        _deactivate_all_rules()


def test_a_device_outside_the_safe_list_is_refused() -> None:
    activate_guard_files_rules([])
    try:
        with pytest.raises(Exception, match="rule"):
            open("/dev/tty", "rb")
    finally:
        _deactivate_all_rules()


def test_a_read_only_device_cannot_be_written() -> None:
    activate_guard_files_rules([])
    try:
        with pytest.raises(Exception, match="Cannot write"):
            open("/dev/urandom", "wb")
    finally:
        _deactivate_all_rules()


def test_a_file_rule_covers_that_file_and_not_a_name_it_prefixes(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)
    other = tmp_path / "pipe2"
    os.mkfifo(other)
    activate_guard_files_rules([ConfigLine(f"expose-rw={fifo}", Path(), 0)])
    try:
        fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
        os.close(fd)
        with pytest.raises(Exception, match="rule"):
            os.open(other, os.O_RDWR | os.O_NONBLOCK)
    finally:
        _deactivate_all_rules()


def test_a_learned_special_file_yields_a_file_rule_not_its_directory(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe"
    os.mkfifo(fifo)

    with (
        patch.dict("pysandboxes.guard_files._special_env", {}, clear=True),
        patch.dict("pysandboxes.guard_files._special_home", {}, clear=True),
    ):
        rules = generate_rules({guard_files.LearnFileRule(fifo, False)})

    assert rules == [f"expose-ro={fifo}"]


def test_a_learned_safe_device_yields_no_rule() -> None:
    assert generate_rules({guard_files.LearnFileRule(Path(NULL), True)}) == []


def test_a_learned_regular_file_still_yields_its_directory(tmp_path: Path) -> None:
    data = tmp_path / "data.txt"
    data.write_text("x")

    assert generate_rules({guard_files.LearnFileRule(data, False)}) == generate_rules(
        {guard_files.LearnFileRule(tmp_path, False)}
    )


def test_the_test_host_has_the_device_kinds_the_rules_name() -> None:
    assert stat.S_ISCHR(os.stat(NULL).st_mode)
