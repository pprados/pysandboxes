# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The profile rules become ``smolvm machine run`` flags: what is not enforced is reported, never approximated."""

import logging
import sys
from pathlib import Path

import pytest

from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.guard_socket import SocketRules
from pysandboxes.guard_socket import parse_rules as parse_socket_rules
from pysandboxes.remote.smolvm_rules import network_args, volume_args
from pysandboxes.sb_types import ConfigLine


def _net(*lines: str) -> AllRules:
    parsed, *_ = parse_socket_rules([ConfigLine(line, Path("profile"), 1) for line in lines], [])
    return EmptyRules._replace(socket_rules=SocketRules(list(parsed)))


def _expose(*entries: tuple[str, bool]) -> AllRules:
    return EmptyRules._replace(
        file_rules=tuple(FSExposeRule(path, write, ConfigLine("", Path("profile"), 1)) for path, write in entries)
    )


class TestNetworkArgs:
    def test_no_rule_leaves_the_network_off(self) -> None:
        assert network_args(EmptyRules) == []

    def test_an_allowed_destination_turns_the_network_on_with_an_allow_list(self) -> None:
        assert network_args(_net("net=ALLOW|TCP|1.1.1.1|*|OUT")) == ["--net", "--allow-cidr", "1.1.1.1/32"]

    def test_a_destination_is_listed_once(self) -> None:
        args = network_args(_net("net=ALLOW|TCP|1.1.1.1|80|OUT", "net=ALLOW|TCP|1.1.1.1|443|OUT"))

        assert args.count("1.1.1.1/32") == 1

    def test_an_inbound_rule_opens_nothing(self) -> None:
        assert network_args(_net("net=ALLOW|TCP|*|4242|IN")) == []

    def test_a_port_cannot_be_enforced_and_is_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            args = network_args(_net("net=ALLOW|TCP|1.1.1.1|443|OUT"))

        assert args == ["--net", "--allow-cidr", "1.1.1.1/32"]
        assert "1.1.1.1" in caplog.text and "port" in caplog.text and "not enforced" in caplog.text

    def test_a_port_on_any_address_is_never_widened_to_the_internet(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            args = network_args(_net("net=ALLOW|TCP|*|53|OUT"))

        assert args == []
        assert "0.0.0.0/0" in caplog.text and "stays closed" in caplog.text

    def test_every_port_on_any_address_is_what_the_rule_says(self) -> None:
        assert network_args(_net("net=ALLOW|TCP|*|*|OUT")) == ["--net", "--allow-cidr", "0.0.0.0/0"]

    def test_every_port_is_not_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            network_args(_net("net=ALLOW|TCP|1.1.1.1|*|OUT"))

        assert caplog.text == ""

    def test_a_udp_port_is_enforced(self) -> None:
        args = network_args(_net("net=ALLOW|UDP|1.1.1.1|53|OUT"))

        assert args == ["--net", "--allow-udp", "1.1.1.1/32:53"]

    def test_every_udp_port_has_no_suffix(self) -> None:
        assert network_args(_net("net=ALLOW|UDP|1.1.1.1|*|OUT")) == ["--net", "--allow-udp", "1.1.1.1/32"]

    def test_a_denied_range_inside_an_allowed_one_is_denied(self) -> None:
        args = network_args(_net("net=ALLOW|TCP|10.0.0.0/8|*|OUT", "net=DENY|TCP|10.1.0.0/16|*|OUT"))

        assert args == ["--net", "--allow-cidr", "10.0.0.0/8", "--deny-cidr", "10.1.0.0/16"]

    def test_an_ipv6_destination_is_reported_and_left_closed(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            args = network_args(_net("net=ALLOW|TCP|2606:4700::/32|*|OUT"))

        assert args == []
        assert "IPv6" in caplog.text and "not enforced" in caplog.text


class TestVolumeArgs:
    def test_a_directory_is_mounted_at_the_same_path(self, tmp_path: Path) -> None:
        assert volume_args(_expose((str(tmp_path) + "/", True))) == ["-v", f"{tmp_path}:{tmp_path}"]

    def test_read_only_is_the_default_flag_of_a_read_only_rule(self, tmp_path: Path) -> None:
        assert volume_args(_expose((str(tmp_path) + "/", False))) == ["-v", f"{tmp_path}:{tmp_path}:ro"]

    def test_the_narrower_right_wins_for_a_path_exposed_both_ways(self, tmp_path: Path) -> None:
        args = volume_args(_expose((str(tmp_path) + "/", True), (str(tmp_path) + "/", False)))

        assert args == ["-v", f"{tmp_path}:{tmp_path}:ro"]

    @pytest.mark.parametrize("path", ["/usr/", "/lib/", "/etc/", "/dev/", "/proc/", "/usr/lib/python3/"])
    def test_what_the_image_owns_is_never_replaced_by_the_host(self, path: str) -> None:
        assert volume_args(_expose((path, False))) == []

    def test_an_ignore_rule_cannot_be_enforced_inside_a_mounted_directory_and_is_reported(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        rules = _expose((str(tmp_path) + "/", False))
        rules = rules._replace(file_rules=(*rules.file_rules, IgnoreRule(".env", ConfigLine("", Path("profile"), 1))))

        with caplog.at_level(logging.WARNING):
            args = volume_args(rules)

        assert args == ["-v", f"{tmp_path}:{tmp_path}:ro"], "the directory is still mounted whole"
        assert ".env" in caplog.text and "not enforced" in caplog.text

    @pytest.mark.parametrize("prefix", [sys.prefix, sys.base_prefix])
    def test_the_host_interpreter_is_not_mounted_the_guest_has_its_own(self, prefix: str) -> None:
        assert volume_args(_expose((prefix + "/", False), (prefix + "/lib/", False))) == []

    def test_a_missing_path_is_left_out(self, tmp_path: Path) -> None:
        assert volume_args(_expose((str(tmp_path / "missing") + "/", False))) == []

    def test_a_file_cannot_be_mounted_alone_and_is_reported(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        file = tmp_path / "one.txt"
        file.write_text("x")

        with caplog.at_level(logging.WARNING):
            args = volume_args(_expose((str(file), False)))

        assert args == []
        assert str(file) in caplog.text and "directories only" in caplog.text
