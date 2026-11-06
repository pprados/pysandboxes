# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_files import FSExposeRule
from pysandboxes.guard_socket import SocketRules
from pysandboxes.guard_socket import parse_rules as socket_parse_rules
from pysandboxes.remote.endpoint import UNIX, Endpoint
from pysandboxes.remote.libkrun_sse_daemon import LibkrunSSEDaemon, _wants_network
from pysandboxes.sb_types import ConfigLine

_MODULE = "pysandboxes.remote.libkrun_sse_daemon"


def _socket_rules(*lines: str) -> SocketRules:
    rules, *_ = socket_parse_rules([ConfigLine(line, Path(), 0) for line in lines], [])
    return SocketRules(list(rules))


def _daemon(tmp_path: Path) -> LibkrunSSEDaemon:
    daemon = LibkrunSSEDaemon(token="test_token")
    daemon.port = 4242
    daemon.endpoint = Endpoint(UNIX, path=str(tmp_path / "s"))
    return daemon


def _config(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "libkrun_config.json").read_text(encoding="utf-8"))


@patch(f"{_MODULE}.os.access", return_value=True)
@patch(f"{_MODULE}.find_libkrun", return_value="/usr/lib/libkrun.so")
@patch(f"{_MODULE}.find_libkrunfw", return_value="/usr/lib/libkrunfw.so")
def test_unavailable_reason_none(mock_fw, mock_lib, mock_access) -> None:
    assert LibkrunSSEDaemon.unavailable_reason() is None


@patch(f"{_MODULE}.os.access", return_value=False)
def test_unavailable_reason_no_kvm(mock_access) -> None:
    assert LibkrunSSEDaemon.unavailable_reason() == "host lacks read/write access to /dev/kvm"


def test_subprocess_cmd_runs_the_launcher_on_its_config(tmp_path: Path) -> None:
    cmd, _ = _daemon(tmp_path).subprocess_cmd(EmptyRules, envs={}, pipe_path=tmp_path / "pipe", temp=tmp_path)

    assert cmd == [
        sys.executable,
        "-m",
        "pysandboxes.remote.libkrun_launcher",
        "--config",
        str(tmp_path / "libkrun_config.json"),
    ]


def test_without_an_outgoing_rule_the_guest_gets_no_network_device(tmp_path: Path) -> None:
    rules = EmptyRules._replace(socket_rules=_socket_rules("net=ALLOW|TCP|*|8080|IN"))

    _daemon(tmp_path).subprocess_cmd(rules, envs={}, pipe_path=tmp_path / "pipe", temp=tmp_path)

    assert _config(tmp_path)["net"] is None
    assert not (tmp_path / "net.rules").exists()


def test_an_outgoing_rule_builds_a_filtered_network(tmp_path: Path) -> None:
    rules = EmptyRules._replace(socket_rules=_socket_rules("net=ALLOW|TCP|10.1.2.3|443|OUT"))

    _daemon(tmp_path).subprocess_cmd(rules, envs={}, pipe_path=tmp_path / "pipe", temp=tmp_path)

    net = _config(tmp_path)["net"]
    assert net["cmd"][:5] == ["unshare", "--user", "--map-root-user", "--net", "--"]
    filter_text = (tmp_path / "net.rules").read_text(encoding="utf-8")
    assert ":OUTPUT DROP" in filter_text and "10.1.2.3" in filter_text
    # The micro-VM stays out of the namespace: only the network stack is started there.
    assert net["cmd"][-2].index("iptables-restore") < net["cmd"][-2].index("exec")


def test_missing_network_tool_is_reported(tmp_path: Path) -> None:
    rules = EmptyRules._replace(socket_rules=_socket_rules("net=ALLOW|TCP|10.1.2.3|443|OUT"))

    with patch(f"{_MODULE}.which_command", return_value=None), pytest.raises(SandBoxError, match="not found"):
        _daemon(tmp_path).subprocess_cmd(rules, envs={}, pipe_path=tmp_path / "pipe", temp=tmp_path)


def test_wants_network_only_for_an_allowed_outgoing_rule() -> None:
    assert not _wants_network(EmptyRules)
    assert not _wants_network(EmptyRules._replace(socket_rules=_socket_rules("net=DENY|TCP|*|443|OUT")))
    assert not _wants_network(EmptyRules._replace(socket_rules=_socket_rules("net=ALLOW|TCP|*|443|IN")))
    assert _wants_network(EmptyRules._replace(socket_rules=_socket_rules("net=ALLOW|TCP|*|443|OUT")))


def test_a_directory_is_shared_with_the_mode_of_its_rule(tmp_path: Path) -> None:
    read_only, read_write = tmp_path / "ro", tmp_path / "rw"
    read_only.mkdir()
    read_write.mkdir()
    rules: AllRules = EmptyRules._replace(
        file_rules=(FSExposeRule(str(read_only), False, None), FSExposeRule(str(read_write), True, None))  # type: ignore[arg-type]
    )

    _daemon(tmp_path).subprocess_cmd(rules, envs={}, pipe_path=tmp_path / "pipe", temp=tmp_path)

    shares = {m["host_path"]: m["readonly"] for m in _config(tmp_path)["mounts"]}
    assert shares == {str(read_only.resolve()): True, str(read_write.resolve()): False}


def test_the_guest_receives_the_environment_of_the_rules_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIBKRUN_SECRET", "x")
    rules = EmptyRules._replace(envs={"ALLOWED": "1"})

    _daemon(tmp_path).subprocess_cmd(rules, envs={}, pipe_path=tmp_path / "pipe", temp=tmp_path)

    assert _config(tmp_path)["envs"] == {"ALLOWED": "1"}
