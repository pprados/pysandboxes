# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Rule parsing, daemon command and chroot roots of the unshare provider."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from pysandboxes.remote import main_sandbox
from pysandboxes.remote.unshare_sse_daemon import UnshareSSEDaemon
from pysandboxes.sb_types import ConfigLine


def _line(text: str) -> ConfigLine:
    return ConfigLine(text, Path("p"), 1)


def _optimize(level: int) -> Any:
    fake_sys = SimpleNamespace(executable=sys.executable, flags=SimpleNamespace(optimize=level))
    return patch("pysandboxes.remote.unshare_sse_daemon.sys", fake_sys)


class TestParseRules:
    def test_unshare_rules_become_parameters_and_the_others_are_returned(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        other = _line("env=ALLOW|X")

        params, rest = daemon.parse_rules([_line("unshare.flag=a=b"), other, _line("unshare.bare")], [])

        assert dict(params) == {"flag": "a=b", "bare": ""}
        assert rest == [other]

    def test_a_rule_merely_containing_the_prefix_is_not_a_parameter(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        line = _line("xunshare.a=b")

        params, rest = daemon.parse_rules([line], [])

        assert dict(params) == {}
        assert rest == [line]

    def test_the_last_value_of_a_key_wins(self) -> None:
        params, _ = UnshareSSEDaemon("tok").parse_rules([_line("unshare.k=1"), _line("unshare.k=2")], [])

        assert dict(params) == {"k": "2"}

    def test_no_rule_gives_nothing(self) -> None:
        params, rest = UnshareSSEDaemon("tok").parse_rules([], [])

        assert dict(params) == {}
        assert rest == []


class TestDaemonCommand:
    def test_the_command_runs_main_sandbox_unbuffered(self) -> None:
        with _optimize(0):
            cmd = UnshareSSEDaemon("tok")._build_daemon_cmd()

        assert cmd == [sys.executable, "-u", "-m", main_sandbox.__name__]

    @pytest.mark.parametrize("level", [1, 2])
    def test_the_optimisation_level_is_forwarded(self, level: int) -> None:
        with _optimize(level):
            cmd = UnshareSSEDaemon("tok", python_args=["-X", "dev"])._build_daemon_cmd()

        assert cmd == [sys.executable, "-u", "-" + "O" * level, "-X", "dev", "-m", main_sandbox.__name__]

    def test_the_python_arguments_precede_the_module(self) -> None:
        with _optimize(0):
            cmd = UnshareSSEDaemon("tok", python_args=["-W", "error"])._build_daemon_cmd()

        assert cmd[-4:] == ["-W", "error", "-m", main_sandbox.__name__]


class TestChrootRoots:
    def test_each_launch_gets_its_own_existing_directory(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        first, second = daemon._make_chroot_dir(), daemon._make_chroot_dir()
        try:
            assert first != second
            assert os.path.isdir(first) and os.path.isdir(second)
            assert daemon._chroot_dirs == [first, second]
        finally:
            daemon._remove_chroot_dirs()

    def test_a_root_that_cannot_be_removed_does_not_stop_the_others(self) -> None:
        daemon = UnshareSSEDaemon("tok")
        first, second = daemon._make_chroot_dir(), daemon._make_chroot_dir()
        os.rmdir(first)

        daemon._remove_chroot_dirs()

        assert not os.path.exists(second)
        assert daemon._chroot_dirs == []

    def test_a_non_empty_root_is_left_alone_and_forgotten(self, tmp_path: Path) -> None:
        daemon = UnshareSSEDaemon("tok")
        root = daemon._make_chroot_dir()
        (Path(root) / "kept").write_text("x")
        try:
            daemon._remove_chroot_dirs()

            assert (Path(root) / "kept").exists()
            assert daemon._chroot_dirs == []
        finally:
            (Path(root) / "kept").unlink()
            os.rmdir(root)
