# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The guest sees the host through a few shares, from which its init script binds exactly what the rules expose."""

import logging
import subprocess
import sys
from pathlib import Path

import pytest

from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.remote.smolvm_root import STAGE, exposures, init_script, mask_targets, shares, volumes
from pysandboxes.sb_types import ConfigLine


def _line() -> ConfigLine:
    return ConfigLine("", Path("profile"), 1)


def _rules(*entries: tuple[str, bool]) -> AllRules:
    return EmptyRules._replace(file_rules=tuple(FSExposeRule(path, write, _line()) for path, write in entries))


class TestExposures:
    def test_a_read_only_rule_is_bound_and_a_read_write_directory_gets_a_share(self, tmp_path: Path) -> None:
        ro, rw = tmp_path / "ro", tmp_path / "rw"
        ro.mkdir()
        rw.mkdir()

        assert exposures(_rules((f"{ro}/", False), (f"{rw}/", True))) == ([str(ro)], [str(rw)])

    def test_the_narrower_right_wins_for_a_path_exposed_both_ways(self, tmp_path: Path) -> None:
        assert exposures(_rules((f"{tmp_path}/", True), (f"{tmp_path}/", False))) == ([str(tmp_path)], [])

    def test_a_file_can_be_exposed_read_only(self, tmp_path: Path) -> None:
        file = tmp_path / "one.txt"
        file.write_text("x")

        assert exposures(_rules((str(file), False))) == ([str(file)], [])

    def test_a_file_cannot_be_exposed_read_write_and_is_reported(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        file = tmp_path / "one.txt"
        file.write_text("x")

        with caplog.at_level(logging.WARNING):
            result = exposures(_rules((str(file), True)))

        assert result == ([str(file)], [])
        assert str(file) in caplog.text and "read-only" in caplog.text

    @pytest.mark.parametrize("path", ["/usr/", "/lib/", "/etc/", "/dev/", "/proc/", "/usr/lib/python3/"])
    def test_what_the_image_owns_is_never_replaced_by_the_host(self, path: str) -> None:
        assert exposures(_rules((path, False))) == ([], [])

    @pytest.mark.parametrize("prefix", [sys.prefix, sys.base_prefix])
    def test_the_host_interpreter_is_not_exposed_the_guest_has_its_own(self, prefix: str) -> None:
        assert exposures(_rules((prefix + "/", False), (prefix + "/lib/", False))) == ([], [])

    def test_a_missing_path_is_left_out(self, tmp_path: Path) -> None:
        assert exposures(_rules((f"{tmp_path / 'missing'}/", False))) == ([], [])

    def test_the_paths_the_provider_needs_come_after_the_rules(self, tmp_path: Path) -> None:
        ro = tmp_path / "ro"
        extra = tmp_path / "extra"
        ro.mkdir()
        extra.mkdir()

        assert exposures(_rules((f"{ro}/", False)), extra_ro=[str(extra)])[0] == [str(ro), str(extra)]


class TestShares:
    def test_paths_under_the_same_top_directory_share_one_device(self) -> None:
        assert shares(["/home/a/x", "/home/a/y/z"]) == [("/home/a", f"{STAGE}/host0")]

    def test_paths_under_different_top_directories_get_a_device_each(self) -> None:
        assert shares(["/home/a/x", "/opt/tool"]) == [("/home/a/x", f"{STAGE}/host0"), ("/opt/tool", f"{STAGE}/host1")]

    def test_a_file_is_shared_through_its_directory(self, tmp_path: Path) -> None:
        file = tmp_path / "one.txt"
        file.write_text("x")

        assert shares([str(file)]) == [(str(tmp_path), f"{STAGE}/host0")]

    def test_the_root_of_the_host_is_never_shared(self) -> None:
        assert all(host != "/" for host, _ in shares(["/home/a", "/opt/b", "/srv/c"]))

    def test_no_path_needs_no_share(self) -> None:
        assert shares([]) == []


class TestVolumes:
    def test_each_share_is_read_only_and_each_writable_directory_has_its_own(self) -> None:
        assert volumes(["/home/a/x"], ["/srv/w"]) == [
            "-v",
            f"/home/a/x:{STAGE}/host0:ro",
            "-v",
            f"/srv/w:{STAGE}/rw0",
        ]


class TestMaskTargets:
    def test_a_file_an_ignore_rule_names_is_masked_inside_an_exposed_directory(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("SECRET")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / ".env").write_text("SECRET")
        rules = _rules((f"{tmp_path}/", False))
        rules = rules._replace(file_rules=(*rules.file_rules, IgnoreRule(".env", _line())))

        masks = dict(mask_targets(rules, "/nowhere", [str(tmp_path)]))

        assert masks == {str(tmp_path / ".env"): False, str(tmp_path / "sub" / ".env"): False}

    def test_a_directory_is_masked_as_a_directory(self, tmp_path: Path) -> None:
        (tmp_path / "secrets").mkdir()
        rules = _rules((f"{tmp_path}/", False))
        rules = rules._replace(file_rules=(*rules.file_rules, IgnoreRule("secrets", _line())))

        assert dict(mask_targets(rules, "/nowhere", [str(tmp_path)])) == {str(tmp_path / "secrets"): True}

    def test_nothing_is_masked_without_an_ignore_rule(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("SECRET")

        assert mask_targets(_rules((f"{tmp_path}/", False)), str(tmp_path), [str(tmp_path)]) == []


def _script(**overrides: object) -> str:
    args: dict[str, object] = dict(
        ro=["/home/a/x", "/home/a/x/inner"],
        rw=["/srv/w"],
        masks=[("/home/a/x/.env", False), ("/home/a/x/secrets", True)],
        cwd="/home/a/x",
        uid=1000,
        gid=100,
        env={"A": "1", "B": "two words"},
        command=["/usr/local/bin/python", "-u", "-m", "pysandboxes.remote.main_sandbox"],
    )
    args.update(overrides)
    return init_script(**args)  # type: ignore[arg-type]


class TestInitScript:
    def test_it_is_valid_shell(self, tmp_path: Path) -> None:
        file = tmp_path / "init.sh"
        file.write_text(_script())

        assert subprocess.run(["sh", "-n", str(file)], capture_output=True).returncode == 0

    def test_a_read_only_path_is_bound_from_its_share_and_made_read_only(self) -> None:
        script = _script()

        assert f"mount --bind {STAGE}/host0 /home/a/x" in script
        assert "mount -o remount,bind,ro /home/a/x" in script

    def test_a_path_inside_an_already_bound_directory_is_not_bound_again(self, tmp_path: Path) -> None:
        (tmp_path / "inner").mkdir()

        script = _script(ro=[str(tmp_path), str(tmp_path / "inner")], masks=[], rw=[], cwd=str(tmp_path))

        assert str(tmp_path / "inner") not in script

    def test_a_writable_directory_is_bound_read_write_after_the_read_only_ones(self) -> None:
        script = _script()

        assert f"mount --bind {STAGE}/rw0 /srv/w" in script
        assert script.index("remount,bind,ro /home/a/x") < script.index(f"{STAGE}/rw0 /srv/w")

    def test_a_mask_hides_a_file_with_the_null_device_and_a_directory_with_an_empty_tmpfs(self) -> None:
        script = _script()

        assert "mount --bind /dev/null /home/a/x/.env" in script
        assert "mount -t tmpfs -o ro tmpfs /home/a/x/secrets" in script

    def test_the_shares_are_detached_before_the_command_and_a_share_left_stops_the_guest(self) -> None:
        script = _script()

        assert f"umount -l {STAGE}/host0" in script
        assert f"umount -l {STAGE}/rw0" in script
        assert script.index("umount -l") < script.index("exec setpriv")
        assert "exit 70" in script

    def test_the_command_runs_as_the_host_user_with_no_capability_and_a_clean_environment(self) -> None:
        last = _script().strip().splitlines()[-1]

        assert last.startswith("exec setpriv --reuid=1000 --regid=100 --clear-groups --bounding-set=-all")
        assert "--inh-caps=-all --no-new-privs env -i A=1 B='two words' /usr/local/bin/python -u -m" in last
        assert last.endswith('"$@"')

    def test_the_standard_input_is_given_to_the_user_before_the_privileges_are_dropped(self) -> None:
        script = _script()

        assert "chown 1000:100 /proc/self/fd/0" in script
        assert script.index("chown") < script.index("exec setpriv")

    def test_the_working_directory_is_entered_before_the_command(self) -> None:
        script = _script()

        assert script.index("cd /home/a/x") < script.index("exec setpriv")
