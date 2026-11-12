# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`remote-endpoint=`: the profile key that picks how the host reaches the sandbox."""

from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_provider import parse_remote_endpoint
from pysandboxes.remote import client_subprocess_sse_daemon as csd
from pysandboxes.remote.client_subprocess_sse_daemon import SubProcessDaemon
from pysandboxes.sb_types import ConfigLine
from tests.unit_tests._unix_sockets import requires_unix_sockets


def _lines(*rules: str) -> list[ConfigLine]:
    return [ConfigLine(rule, Path("p"), n) for n, rule in enumerate(rules, 1)]


def test_auto_is_the_default_and_other_rules_pass_through() -> None:
    errors: list = []

    endpoint, others = parse_remote_endpoint(_lines("py-sandbox=true"), errors)

    assert (endpoint, [rule.rule for rule in others], errors) == ("auto", ["py-sandbox=true"], [])


@pytest.mark.parametrize("value", ["unix", "UNIX", " unix "])
def test_unix_is_accepted_and_consumed(value: str) -> None:
    errors: list = []

    endpoint, others = parse_remote_endpoint(_lines(f"remote-endpoint={value}", "a=b"), errors)

    assert (endpoint, [rule.rule for rule in others], errors) == ("unix", ["a=b"], [])


def test_the_last_line_wins() -> None:
    endpoint, _ = parse_remote_endpoint(_lines("remote-endpoint=unix", "remote-endpoint=tcp"), [])

    assert endpoint == "tcp"


@pytest.mark.parametrize("value", ["vsock", "", "pipe"])
def test_an_unknown_transport_is_an_error(value: str) -> None:
    errors: list = []

    endpoint, _ = parse_remote_endpoint(_lines(f"remote-endpoint={value}"), errors)

    assert endpoint == "auto"
    assert len(errors) == 1 and "remote-endpoint" in errors[0][0]


def _daemon(monkeypatch: pytest.MonkeyPatch, *, supported: bool = True) -> SubProcessDaemon:
    monkeypatch.setattr(SubProcessDaemon, "supports_unix_endpoint", supported)
    return SubProcessDaemon("tok")


def _choose(daemon: SubProcessDaemon, mode: str, port: int = -1) -> None:
    daemon._choose_endpoint(EmptyRules._replace(remote_endpoint=mode, port=port))


@requires_unix_sockets
def test_auto_picks_a_unix_socket_when_possible(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = _daemon(monkeypatch)

    _choose(daemon, "auto")

    assert daemon.endpoint is not None and daemon.endpoint.kind == "unix"
    daemon._release_endpoint()
    assert daemon.endpoint is None


def test_tcp_never_picks_a_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = _daemon(monkeypatch)

    _choose(daemon, "tcp")

    assert daemon.endpoint is None


def test_auto_falls_back_to_tcp_for_a_provider_without_support(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = _daemon(monkeypatch, supported=False)

    _choose(daemon, "auto")

    assert daemon.endpoint is None


def test_auto_falls_back_to_tcp_for_a_fixed_port(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = _daemon(monkeypatch)

    _choose(daemon, "auto", port=8123)

    assert daemon.endpoint is None


def test_auto_falls_back_to_tcp_when_no_socket_can_be_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = _daemon(monkeypatch)

    def refuse(_: object) -> None:
        raise PermissionError("AF_UNIX is denied")

    monkeypatch.setattr(csd, "listen_socket", refuse)

    _choose(daemon, "auto")

    assert daemon.endpoint is None and daemon._endpoint_dir is None


def test_unix_is_an_error_where_auto_would_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = _daemon(monkeypatch, supported=False)

    with pytest.raises(SandBoxError, match="remote-endpoint=tcp or auto"):
        _choose(daemon, "unix")


def test_auto_falls_back_to_tcp_when_the_provider_binary_refuses_a_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = _daemon(monkeypatch)
    monkeypatch.setattr(SubProcessDaemon, "unix_endpoint_blocker", lambda self: "the binary is too old")

    _choose(daemon, "auto")

    assert daemon.endpoint is None


def test_unix_is_an_error_when_the_provider_binary_refuses_a_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    daemon = _daemon(monkeypatch)
    monkeypatch.setattr(SubProcessDaemon, "unix_endpoint_blocker", lambda self: "the binary is too old")

    with pytest.raises(SandBoxError, match="the binary is too old"):
        _choose(daemon, "unix")


def test_the_qemu_probe_rejects_a_binary_that_cannot_run() -> None:
    from pysandboxes.remote.qemu_sse_daemon import _qemu_accepts_unix_hostfwd

    assert _qemu_accepts_unix_hostfwd("/nonexistent/qemu-system-x86_64") is False
