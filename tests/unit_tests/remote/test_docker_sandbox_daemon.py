# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The docker-sandbox daemon: profile keys, the guest script and the launch plan, without starting ``sbx``."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_files import FSExposeRule
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote import docker_sandbox_daemon as module
from pysandboxes.remote.docker_sandbox_daemon import DockerSandboxSSEDaemon, guest_script
from pysandboxes.sb_types import ConfigLine

_LINE = ConfigLine("test", Path("profile"), 1)


def _daemon() -> DockerSandboxSSEDaemon:
    daemon = DockerSandboxSSEDaemon("token")
    daemon.port = 4321
    return daemon


def _plan(command: list[str]) -> dict[str, object]:
    return json.loads(command[-1])


class TestProfile:
    def test_the_provider_keys_are_split_from_the_other_lines(self) -> None:
        rules = [ConfigLine("docker-sandbox.cpus=2", Path("p"), 1), ConfigLine("net=ALLOW|TCP|*|*|OUT", Path("p"), 2)]

        params, other = _daemon().parse_rules(rules, [])

        assert dict(params) == {"cpus": "2"} and [rule.rule for rule in other] == ["net=ALLOW|TCP|*|*|OUT"]

    def test_an_unknown_key_is_refused_at_start(self, tmp_path: Path) -> None:
        rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"colour": "red"}))

        with patch.object(module, "which_command", return_value="/usr/bin/sbx"):
            with pytest.raises(SandBoxError, match="does not know docker-sandbox.colour"):
                _daemon().subprocess_cmd(rules, {}, tmp_path / "pipe", tmp_path)

    def test_the_channel_is_a_published_tcp_port(self) -> None:
        daemon = _daemon()

        assert not daemon.supports_unix_endpoint and daemon._sse_bind_host([]) == "0.0.0.0"  # noqa: S104


class TestGuestScript:
    def _script(self, **overrides: object) -> str:
        values: dict[str, object] = {
            "masks": [],
            "cwd": "/work",
            "env": {"HOME": "/tmp"},
            "inherited": (),
            "command": ["/usr/local/bin/python", "-m", "pysandboxes.remote.main_sandbox", "--_config-on-stdin"],
            "python_version": (3, 15),
        }
        values.update(overrides)
        return guest_script(**values)  # type: ignore[arg-type]

    def test_the_payload_drops_every_right_before_it_runs(self) -> None:
        script = self._script()

        assert "setpriv --reuid=2000 --regid=2000 --clear-groups --bounding-set=-all --inh-caps=-all" in script
        assert "--no-new-privs env -i HOME=/tmp" in script and script.rstrip().endswith('"$@"')

    def test_the_guest_python_must_match_the_host(self) -> None:
        script = self._script()

        assert "sys.version_info[:2] == (3, 15)" in script and "exit 72" in script

    def test_masks_come_before_the_privilege_drop(self) -> None:
        script = self._script(masks=[("/work/.env", False), ("/work/keys", True)])

        assert script.index("ctypes") < script.index("setpriv")
        assert '[["/work/.env", false], ["/work/keys", true]]' in script

    def test_no_mask_no_mount_call(self) -> None:
        assert "ctypes" not in self._script()

    def test_inherited_variables_are_passed_through_when_set(self) -> None:
        assert '${HTTPS_PROXY:+HTTPS_PROXY="$HTTPS_PROXY"}' in self._script(inherited=("HTTPS_PROXY",))

    def test_no_proxy_variable_without_the_option(self) -> None:
        assert "PROXY" not in self._script()


class TestPlan:
    def _cmd(self, tmp_path: Path, **params: str) -> list[str]:
        rules = EmptyRules._replace(
            os_sandbox_params=ImmutableDict(params),
            file_rules=(FSExposeRule(f"{tmp_path}/data/", True, _LINE),),
        )
        (tmp_path / "data").mkdir()
        with patch.object(module, "which_command", return_value="/usr/bin/sbx"):
            command, _ = _daemon().subprocess_cmd(rules, {}, tmp_path / "pipe", tmp_path)
        return command

    def test_the_launcher_runs_isolated_with_a_json_plan(self, tmp_path: Path) -> None:
        command = self._cmd(tmp_path)

        assert command[1] == "-I" and command[2].endswith("docker_sandbox_launcher.py")
        assert _plan(command)["name"].startswith("pysb-")  # type: ignore[attr-defined]

    def test_the_writable_directory_is_the_primary_workspace_and_the_package_is_read_only(self, tmp_path: Path) -> None:
        create = _plan(self._cmd(tmp_path))["create"]

        assert str(tmp_path / "data") in create  # type: ignore[operator]
        assert any(arg.endswith(":ro") and arg.startswith(str(module._PACKAGE_DIR)) for arg in create)  # type: ignore[attr-defined]
        assert create[create.index("-p") + 1] == "127.0.0.1:4321:4321"  # type: ignore[index, attr-defined]

    def test_cpus_and_memory_come_from_the_profile(self, tmp_path: Path) -> None:
        create = _plan(self._cmd(tmp_path, cpus="2", mem="1g"))["create"]

        assert create[create.index("--cpus") + 1] == "2" and create[create.index("-m") + 1] == "1g"  # type: ignore[index, attr-defined]

    def test_the_template_defaults_to_the_one_of_this_python(self, tmp_path: Path) -> None:
        create = _plan(self._cmd(tmp_path))["create"]

        assert create[create.index("-t") + 1].startswith("pysandboxes-guest:3.")  # type: ignore[index, attr-defined]

    def test_a_canary_name_must_be_denied(self, tmp_path: Path) -> None:
        assert _plan(self._cmd(tmp_path))["canary"] == "pysb-canary.invalid:443"

    def test_the_proxy_option_adds_the_guard_rule_in_the_guest(self) -> None:
        rules = EmptyRules._replace(os_sandbox_params=ImmutableDict({"proxy": "true"}))

        answer = [(2, 1, 6, "", ("192.168.65.254", 0))]
        with patch("pysandboxes.guard_socket._resolve_with_retry", return_value=answer):
            updated = _daemon().update_rules_and_activate(all_rules=rules, envs={})  # type: ignore[arg-type]

        assert any(rule.mask.ports == (3128,) for rule in updated.socket_rules)

    def test_no_proxy_rule_by_default(self) -> None:
        updated = _daemon().update_rules_and_activate(all_rules=EmptyRules, envs={})  # type: ignore[arg-type]

        assert not list(updated.socket_rules)

    def test_the_guest_can_read_its_interpreter_and_the_package(self) -> None:
        updated = _daemon().update_rules_and_activate(all_rules=EmptyRules, envs={})  # type: ignore[arg-type]

        paths = {rule.path for rule in updated.file_rules if isinstance(rule, FSExposeRule)}
        assert paths == {"/usr/local/", f"{module._PACKAGE_DIR}/"}


class TestProbe:
    def test_a_missing_sbx_is_reported(self) -> None:
        module._probe.cache_clear()
        with patch.object(module, "which_command", return_value=None):
            assert "sbx not found" in (DockerSandboxSSEDaemon.unavailable_reason() or "")
        module._probe.cache_clear()

    def test_checks_are_found_whatever_the_nesting(self) -> None:
        text = json.dumps({"groups": [{"checks": [{"name": "daemon", "status": "pass"}]}]})

        assert module._checks(text) == [{"name": "daemon", "status": "pass"}]

    def test_a_non_json_diagnosis_has_no_check(self) -> None:
        assert module._checks("not json") == []


class TestStaleSandboxes:
    def _cmd(self, daemon: DockerSandboxSSEDaemon, tmp_path: Path) -> list[str]:
        with patch.object(module, "which_command", return_value="/usr/bin/sbx"):
            return daemon.subprocess_cmd(EmptyRules, {}, tmp_path / "pipe", tmp_path)[0]

    def test_a_restart_names_the_sandbox_of_the_previous_launch_for_removal(self, tmp_path: Path) -> None:
        daemon = _daemon()

        first = _plan(self._cmd(daemon, tmp_path))
        second = _plan(self._cmd(daemon, tmp_path))

        assert first["stale"] == [] and second["stale"] == [first["name"]]

    def test_the_owner_of_a_sandbox_is_dead_only_when_its_process_is_gone(self) -> None:
        from pysandboxes.remote.docker_sandbox_launcher import _owner_is_dead

        assert not _owner_is_dead(f"pysb-{os.getpid()}-0123abcd")
        assert _owner_is_dead("pysb-999999999-0123abcd")
        assert not _owner_is_dead("someone-else") and not _owner_is_dead("pysb-notapid-x")
