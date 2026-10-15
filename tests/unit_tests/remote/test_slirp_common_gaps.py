# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Port forwarding spec and temporary files of slirp4netns."""

import logging
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.remote.slirp4netns_common import extract_port_forwards, remove_slirp_temp_files
from pysandboxes.sb_types import ConfigLine

_ANY = IPv4Network("0.0.0.0/0")


def _rule(
    action: Action,
    directions: tuple[Direction, ...],
    ports: range | tuple[int, ...],
    kinds: tuple[Kind, ...] = (Kind.TCP,),
) -> SocketRule:
    return SocketRule(action, SocketMask(kinds, _ANY, ports), directions, ConfigLine("net=x", Path(), 1))


def _spec(*rules: SocketRule, **kwargs: bool) -> str:
    return extract_port_forwards(EmptyRules._replace(socket_rules=tuple(rules)), 9000, **kwargs)


class TestExtractPortForwards:

    def test_an_allowed_incoming_rule_is_forwarded_sorted_by_kind_and_port(self) -> None:
        spec = _spec(
            _rule(Action.ALLOW, (Direction.IN,), (443, 80)),
            _rule(Action.ALLOW, (Direction.IN, Direction.OUT), (53,), (Kind.UDP,)),
        )

        assert spec == "tcp:80 tcp:443 tcp:9000 udp:53"

    @pytest.mark.parametrize(
        "rule",
        [
            _rule(Action.DENY, (Direction.IN,), (80,)),
            _rule(Action.ALLOW, (Direction.OUT,), (80,)),
            _rule(Action.DENY, (Direction.OUT,), (80,)),
        ],
    )
    def test_only_allowed_incoming_rules_are_forwarded(self, rule: SocketRule) -> None:
        assert _spec(rule) == "tcp:9000"

    def test_a_skipped_rule_does_not_hide_the_following_ones(self) -> None:
        spec = _spec(
            _rule(Action.DENY, (Direction.IN,), (80,)),
            _rule(Action.ALLOW, (Direction.OUT,), (81,)),
            _rule(Action.ALLOW, (Direction.IN,), (82,)),
        )

        assert spec == "tcp:82 tcp:9000"

    def test_a_wildcard_range_is_not_forwarded_and_is_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        wildcard = _rule(Action.ALLOW, (Direction.IN,), range(1, 65536))

        with caplog.at_level(logging.WARNING, logger="pysandboxes.remote.slirp4netns_common"):
            spec = _spec(wildcard, _rule(Action.ALLOW, (Direction.IN,), (80,)))

        assert spec == "tcp:80 tcp:9000"
        assert "Cannot forward wildcard port range" in caplog.text

    def test_the_wildcard_report_can_be_turned_off(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="pysandboxes.remote.slirp4netns_common"):
            _spec(_rule(Action.ALLOW, (Direction.IN,), range(1, 65536)), log_wildcard=False)

        assert caplog.text == ""


class TestRemoveSlirpTempFiles:
    def test_both_files_are_removed(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "pid"
        api_socket = tmp_path / "api"
        pid_file.write_text("1")
        api_socket.write_text("")

        remove_slirp_temp_files(str(pid_file), str(api_socket))

        assert not pid_file.exists()
        assert not api_socket.exists()

    def test_missing_or_unset_paths_are_ignored(self, tmp_path: Path) -> None:
        remove_slirp_temp_files(str(tmp_path / "absent"), None)


class TestWideRanges:
    def test_a_small_range_is_forwarded_and_a_wide_one_is_not(self) -> None:
        spec = _spec(
            _rule(Action.ALLOW, (Direction.IN,), range(8000, 8003)),
            _rule(Action.ALLOW, (Direction.IN,), range(1, 5000)),
        )

        assert spec == "tcp:8000 tcp:8001 tcp:8002 tcp:9000"

    def test_a_long_explicit_list_is_forwarded_whole(self) -> None:
        ports = tuple(range(2000, 3500))

        spec = _spec(_rule(Action.ALLOW, (Direction.IN,), ports))

        assert spec.split() == [f"tcp:{p}" for p in sorted((*ports, 9000))]
