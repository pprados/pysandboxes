# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The rules of a profile become ``sbx`` resources, mounts and masks: what cannot be expressed is reported."""

import logging
from pathlib import Path

import pytest

from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.egress_filter import NameRule
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.guard_socket import SocketRules
from pysandboxes.guard_socket import parse_rules as parse_socket_rules
from pysandboxes.remote.docker_sandbox_rules import guest_python_path, is_inside, mask_targets, mounts, sbx_rules
from pysandboxes.sb_types import ConfigLine

_LINE = ConfigLine("test", Path("profile"), 1)


def _net(*lines: str) -> AllRules:
    parsed, *_ = parse_socket_rules([ConfigLine(line, Path("profile"), 1) for line in lines], [])
    return EmptyRules._replace(socket_rules=SocketRules(list(parsed)))


class TestSbxRules:
    def test_no_rule_opens_nothing(self) -> None:
        assert sbx_rules(EmptyRules) == ((), ())

    def test_an_address_and_a_port_become_one_resource(self) -> None:
        assert sbx_rules(_net("net=ALLOW|TCP|1.1.1.1|443|OUT")).allow == ("1.1.1.1:443",)

    def test_every_port_is_an_address_alone(self) -> None:
        assert sbx_rules(_net("net=ALLOW|TCP|1.1.1.1|*|OUT")).allow == ("1.1.1.1",)

    def test_a_cidr_keeps_its_prefix(self) -> None:
        assert sbx_rules(_net("net=ALLOW|TCP|10.0.0.0/8|80|OUT")).allow == ("10.0.0.0/8:80",)

    def test_every_destination_is_all_hosts(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            rules = sbx_rules(_net("net=ALLOW|TCP|*|*|OUT"))

        assert rules.allow == ("**",)
        assert "every destination" in caplog.text

    def test_a_port_on_any_address_is_all_hosts_on_that_port(self) -> None:
        assert sbx_rules(_net("net=ALLOW|TCP|*|53|OUT")).allow == ("**:53",)

    def test_a_deny_rule_is_a_deny_resource(self) -> None:
        assert sbx_rules(_net("net=DENY|TCP|1.1.1.1|*|OUT")).deny == ("1.1.1.1",)

    def test_an_inbound_rule_opens_nothing(self) -> None:
        assert sbx_rules(_net("net=ALLOW|TCP|*|4242|IN")) == ((), ())

    def test_udp_stays_closed_and_is_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            rules = sbx_rules(_net("net=ALLOW|UDP|1.1.1.1|53|OUT"))

        assert rules.allow == ()
        assert "UDP" in caplog.text

    def test_a_long_port_list_is_omitted_and_reported(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            rules = sbx_rules(_net("net=ALLOW|TCP|1.1.1.1|1000-2000|OUT"))

        assert rules.allow == ()
        assert "omits" in caplog.text

    def test_a_pinned_name_is_opened_with_its_address(self) -> None:
        rules = _net("net=ALLOW|TCP|1.1.1.1|443|OUT")._replace(
            pin_dns={"one.example": ((2, 1, 6, "", ("1.1.1.1", 0)),)}  # type: ignore[arg-type]
        )

        assert sbx_rules(rules).allow == ("one.example:443", "1.1.1.1:443")

    @pytest.mark.parametrize(
        ("pattern", "expected"),
        [
            ("example.com", ("example.com", "**.example.com")),
            ("=example.com", ("example.com",)),
            ("*.example.com", ("**.example.com",)),
        ],
    )
    def test_a_runtime_name_rule_keeps_its_scope(self, pattern: str, expected: tuple[str, ...]) -> None:
        rules = EmptyRules._replace(name_rules=(NameRule(True, pattern, ("tcp",)),))

        assert sbx_rules(rules).allow == expected

    def test_a_runtime_name_rule_with_ports(self) -> None:
        rules = EmptyRules._replace(name_rules=(NameRule(True, "=example.com", ("tcp",), ((443, 444),)),))

        assert sbx_rules(rules).allow == ("example.com:443", "example.com:444")

    def test_a_runtime_deny_name_rule_is_a_deny(self) -> None:
        assert sbx_rules(EmptyRules._replace(name_rules=(NameRule(False, "=bad.example"),))).deny == ("bad.example",)

    def test_a_udp_only_name_rule_opens_nothing(self) -> None:
        assert sbx_rules(EmptyRules._replace(name_rules=(NameRule(True, "=u.example", ("udp",)),))).allow == ()


class TestMounts:
    def test_a_directory_rule_is_mounted(self, tmp_path: Path) -> None:
        rules = EmptyRules._replace(file_rules=(FSExposeRule(f"{tmp_path}/", False, _LINE),))

        assert mounts(rules).ro == (str(tmp_path),)

    def test_write_wins_when_a_path_is_exposed_both_ways(self, tmp_path: Path) -> None:
        rules = EmptyRules._replace(
            file_rules=(FSExposeRule(f"{tmp_path}/", False, _LINE), FSExposeRule(f"{tmp_path}/", True, _LINE))
        )

        assert mounts(rules) == ((), (str(tmp_path),))

    def test_what_the_image_owns_is_not_mounted(self) -> None:
        rules = EmptyRules._replace(file_rules=(FSExposeRule("/usr/lib/", False, _LINE),))

        assert mounts(rules) == ((), ())

    def test_a_missing_path_is_not_mounted(self, tmp_path: Path) -> None:
        rules = EmptyRules._replace(file_rules=(FSExposeRule(f"{tmp_path}/absent/", False, _LINE),))

        assert mounts(rules) == ((), ())

    def test_a_writable_file_is_exposed_read_only_and_reported(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        file = tmp_path / "f.txt"
        file.write_text("x")
        rules = EmptyRules._replace(file_rules=(FSExposeRule(str(file), True, _LINE),))

        with caplog.at_level(logging.WARNING):
            assert mounts(rules) == ((str(file),), ())
        assert "read-only" in caplog.text

    def test_the_extra_read_only_paths_of_the_provider_are_added(self, tmp_path: Path) -> None:
        assert mounts(EmptyRules, extra_ro=[str(tmp_path)]).ro == (str(tmp_path),)


class TestMasks:
    def test_no_ignore_rule_masks_nothing(self, tmp_path: Path) -> None:
        assert mask_targets(EmptyRules, str(tmp_path), [str(tmp_path)]) == []

    def test_a_file_and_a_directory_are_found_by_base_name(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("secret")
        (tmp_path / "keys").mkdir()
        rules = EmptyRules._replace(file_rules=(IgnoreRule(".env", _LINE), IgnoreRule("keys", _LINE)))

        found = dict(mask_targets(rules, str(tmp_path), [str(tmp_path)]))

        assert found == {str(tmp_path / ".env"): False, str(tmp_path / "keys"): True}


class TestPythonPath:
    def test_only_exposed_directories_are_kept(self, tmp_path: Path) -> None:
        kept = tmp_path / "lib"
        other = tmp_path / "other"
        kept.mkdir()
        other.mkdir()

        assert guest_python_path([str(kept), str(other)], [str(kept)], str(tmp_path)) == [str(kept)]

    def test_is_inside_matches_the_path_and_what_is_below(self) -> None:
        assert is_inside("/a/b", ["/a"]) and is_inside("/a", ["/a"]) and not is_inside("/ab", ["/a"])
