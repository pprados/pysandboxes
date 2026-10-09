# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Defects of the environment guard and of the configuration core."""

import logging
import os
import sys
from pathlib import Path

import pytest

from pysandboxes import guard_envs, guard_provider, tools
from pysandboxes.e import ConfigSyntaxError
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.py_sandbox import _parse_include, parse_config
from pysandboxes.sb_types import ConfigLine

_SOURCE = {"DUMMY_KEY": "abc", "OTHER_KEY": "def", "DUMMY_NAME": "ghi"}


def _envs(*lines: str) -> dict[str, str]:
    errors: list[ErrorMsg] = []
    _, envs, unclaimed = guard_envs.parse_rules(
        [ConfigLine(line, Path("profile"), ln) for ln, line in enumerate(lines, 1)], _SOURCE, errors
    )
    assert errors == []
    assert unclaimed == []
    return dict(envs)


@pytest.mark.parametrize(
    "lines",
    [
        ("env=*_KEY=${*_KEY}", "unenv=DUMMY_KEY"),
        ("unenv=DUMMY_KEY", "env=*_KEY=${*_KEY}"),
    ],
)
def test_unenv_does_not_depend_on_line_order(lines: tuple[str, str]) -> None:
    assert _envs(*lines) == {"OTHER_KEY": "def"}


def test_unenv_accepts_a_glob() -> None:
    assert _envs("env=DUMMY_*=${DUMMY_*}", "env=OTHER_KEY=${OTHER_KEY}", "unenv=*_KEY") == {"DUMMY_NAME": "ghi"}


def test_wildcard_env_applies_its_fixed_value() -> None:
    assert _envs("env=*_KEY=fixed") == {"DUMMY_KEY": "fixed", "OTHER_KEY": "fixed"}


def test_wildcard_env_applies_its_default() -> None:
    assert _envs("env=*_KEY=${*_KEY:-x}") == {"DUMMY_KEY": "abc", "OTHER_KEY": "def"}


def test_exact_env_beats_wildcard_whatever_the_order() -> None:
    assert _envs("env=DUMMY_KEY=fixed", "env=*_KEY=${*_KEY}") == {"DUMMY_KEY": "fixed", "OTHER_KEY": "def"}


def test_command_line_port_beats_profile_port(tmp_path: Path) -> None:
    errors: list[ErrorMsg] = []
    rules = [ConfigLine("port=9000", Path(), 0), ConfigLine("port=8000", tmp_path / "profile", 1)]
    port, *_ = guard_provider.parse_rules(tmp_path / "profile", rules, errors)
    assert errors == []
    assert port == 9000


def test_command_line_port_beats_two_file_sources(tmp_path: Path) -> None:
    # G18: CLI must win over any number of conflicting port= lines from profile and includes.
    errors: list[ErrorMsg] = []
    rules = [
        ConfigLine("port=9000", Path(), 0),
        ConfigLine("port=8000", tmp_path / "profile", 1),
        ConfigLine("port=8001", tmp_path / "included", 1),
    ]
    port, provider, *_ = guard_provider.parse_rules(tmp_path / "profile", rules, errors)
    assert errors == []
    assert port == 9000
    assert provider != "error"


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs a non-root POSIX user")
def test_unreadable_include_is_a_configuration_error(tmp_path: Path) -> None:
    unreadable = tmp_path / "locked.profile"
    unreadable.write_text("learn=false\n")
    unreadable.chmod(0)
    try:
        with pytest.raises(ConfigSyntaxError, match="locked.profile"):
            _parse_include(
                tmp_path, {tmp_path / "root"}, [ConfigLine('include "locked.profile"', tmp_path / "root", 1)]
            )
    finally:
        unreadable.chmod(0o600)


def test_missing_include_is_ignored_quietly(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG, logger="pysandboxes.py_sandbox"):
        result = _parse_include(tmp_path, {tmp_path / "root"}, [ConfigLine('include "absent"', tmp_path / "root", 1)])
    assert result == []
    assert [r.levelno for r in caplog.records if "absent" in r.getMessage()] == [logging.DEBUG]


def test_nested_bare_include_is_resolved_next_to_the_including_file(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "middle").write_text('include "leaf"\n')
    (tmp_path / "sub" / "leaf").write_text("env=DUMMY_KEY=abc\n")
    (tmp_path / "leaf").write_text("env=DUMMY_KEY=wrong\n")
    rules = _parse_include(
        tmp_path, {tmp_path / "root"}, [ConfigLine(f'include "{tmp_path}/sub/middle"', tmp_path / "root", 1)]
    )
    assert [r.rule for r in rules] == ["env=DUMMY_KEY=abc"]


def test_self_include_through_a_relative_path_is_loaded_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "root.profile").write_text('include "./root.profile"\nos-sandbox=subprocess\nport=8000\n')
    config = [
        ConfigLine("os-sandbox=subprocess", Path("root.profile"), 2),
        ConfigLine("port=8000", Path("root.profile"), 3),
    ]
    config.insert(0, ConfigLine('include "./root.profile"', Path("root.profile"), 1))
    rules = parse_config(config, Path("root.profile"), envs={})
    assert rules.port == 8000


def test_immutable_dict_has_no_instance_dict() -> None:
    d = ImmutableDict({"DUMMY_KEY": "abc"})
    with pytest.raises(AttributeError):
        d.extra = 1  # type: ignore[attr-defined]


def test_immutable_dict_from_pairs_keeps_keys_and_values_aligned() -> None:
    with pytest.raises(ValueError):
        ImmutableDict([(), ("DUMMY_KEY", "abc")])  # type: ignore[arg-type]
    d = ImmutableDict([("DUMMY_KEY", "abc"), ("DUMMY_KEY", "def")])
    assert len(d) == 1
    assert dict(d) == {"DUMMY_KEY": "def"}


def test_immutable_dict_equals_a_plain_dict() -> None:
    d = ImmutableDict({"DUMMY_KEY": "abc", "OTHER_KEY": "def"})
    assert d == {"OTHER_KEY": "def", "DUMMY_KEY": "abc"}
    assert not d != {"OTHER_KEY": "def", "DUMMY_KEY": "abc"}
    assert d == ImmutableDict({"OTHER_KEY": "def", "DUMMY_KEY": "abc"})
    assert hash(d) == hash(ImmutableDict({"OTHER_KEY": "def", "DUMMY_KEY": "abc"}))
    assert d != {"DUMMY_KEY": "abc"}


def test_immutable_dict_never_equals_its_internal_tuple() -> None:
    """The storage tuple is an implementation detail: equal objects must hash alike."""
    d = ImmutableDict({"a": 1})
    raw = (("a",), (1,))
    assert d != raw
    assert raw != d
    assert not d == raw


def test_unresolvable_executable_error_is_formatted(tmp_path: Path) -> None:
    missing = tmp_path / "python"
    missing.symlink_to(tmp_path / "absent")
    with pytest.raises(RuntimeError) as exc:
        tools.follow_links_executable(missing, set())
    assert len(exc.value.args) == 1
    assert str(missing) in exc.value.args[0]
