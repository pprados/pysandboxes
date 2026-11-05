# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`remote-endpoint=`: the profile key that picks how the host reaches the sandbox."""

from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxError
from pysandboxes.guard_provider import parse_remote_endpoint
from pysandboxes.remote.client_subprocess_sse_daemon import SubProcessDaemon
from pysandboxes.sb_types import ConfigLine


def _lines(*rules: str) -> list[ConfigLine]:
    return [ConfigLine(rule, Path("p"), n) for n, rule in enumerate(rules, 1)]


def test_tcp_is_the_default_and_other_rules_pass_through() -> None:
    errors: list = []

    endpoint, others = parse_remote_endpoint(_lines("py-sandbox=true"), errors)

    assert (endpoint, [rule.rule for rule in others], errors) == ("tcp", ["py-sandbox=true"], [])


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

    assert endpoint == "tcp"
    assert len(errors) == 1 and "remote-endpoint" in errors[0][0]


async def test_a_provider_that_cannot_hand_down_a_socket_refuses_unix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SubProcessDaemon, "supports_unix_endpoint", False)
    daemon = SubProcessDaemon("tok")

    with pytest.raises(SandBoxError, match="remote-endpoint=tcp"):
        await daemon._start(
            EmptyRules._replace(remote_endpoint="unix"), envs={}, log_level=10, init_fn=None  # type: ignore[arg-type]
        )
