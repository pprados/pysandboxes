# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Routes and log setup of the SSE server, and the loopback and filter steps of the sandbox main."""

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn
from fastapi import HTTPException

from pysandboxes.remote import main_sandbox
from pysandboxes.remote.sse_server_daemon import SSEServerDaemon, create_uvicorn_daemon


class _Stream:
    def __init__(self, name: str) -> None:
        self.name = name

    def write(self, text: str) -> None:
        pass

    def flush(self) -> None:
        pass


@pytest.fixture
def server_config(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """The arguments `create_uvicorn_daemon` hands to uvicorn, which is replaced so no logging is reconfigured."""
    captured: dict[str, Any] = {}

    def config(app: Any, **kwargs: Any) -> SimpleNamespace:
        captured.update(kwargs, app=app)
        return SimpleNamespace()

    monkeypatch.setattr(uvicorn, "Config", config)
    monkeypatch.setattr(uvicorn, "Server", lambda config: config)
    return captured


def _routes(app: Any) -> dict[tuple[str, str], Any]:
    return {(route.path, method): route.endpoint for route in app.routes for method in route.methods}


def test_the_server_exposes_ping_and_rpc(server_config: dict[str, Any]) -> None:
    create_uvicorn_daemon("tok", "127.0.0.1", 1234)

    routes = _routes(server_config["app"])
    assert asyncio.run(routes[("/ping", "GET")]()) == {"message": "OK"}
    assert ("/rpc", "POST") in routes
    assert (server_config["host"], server_config["port"]) == ("127.0.0.1", 1234)


def test_rpc_refuses_a_wrong_token_then_a_stopping_daemon(
    server_config: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    create_uvicorn_daemon("tok", "127.0.0.1", 1234)
    rpc = _routes(server_config["app"])[("/rpc", "POST")]
    payload = SimpleNamespace(session_id="s", function="m:f", args="", kwargs="")

    def request(authorization: str) -> Any:
        return SimpleNamespace(headers={"Authorization": authorization})

    with pytest.raises(HTTPException) as wrong:
        asyncio.run(rpc(request("Bearer other"), payload))
    assert wrong.value.status_code == 401

    monkeypatch.setattr("pysandboxes._os_sandbox.is_accept_incoming_call", lambda: False)
    with pytest.raises(HTTPException) as stopping:
        asyncio.run(rpc(request("Bearer tok"), payload))
    assert stopping.value.status_code == 503


@pytest.mark.parametrize(
    ("stream_name", "expected"),
    [
        ("<stderr>", "ext://sys.stderr"),
        ("<stdout>", "ext://sys.stdout"),
        ("/var/log/app.log", "ext:/var/log/app.log"),
    ],
)
def test_the_uvicorn_log_stream_follows_the_stream_of_the_existing_handler(
    server_config: dict[str, Any], monkeypatch: pytest.MonkeyPatch, stream_name: str, expected: str
) -> None:
    monkeypatch.setattr(logging.getLogger("uvicorn"), "handlers", [logging.StreamHandler(_Stream(stream_name))])  # type: ignore[arg-type]

    create_uvicorn_daemon("tok", "127.0.0.1", 1234)

    assert server_config["log_config"]["handlers"]["default"]["stream"] == expected


def test_a_new_server_daemon_is_stopped() -> None:
    assert SSEServerDaemon("tok", port=1234).stopped is True


class TestApplyNetfilterCommands:
    @pytest.fixture
    def calls(self, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
        recorded: list[list[str]] = []

        def run(cmd: list[str], **kwargs: Any) -> Any:
            recorded.append(cmd)
            return SimpleNamespace(returncode=0, stderr=b"")

        monkeypatch.setattr(main_sandbox.subprocess, "run", run)
        monkeypatch.setattr(main_sandbox, "_IPTABLES_RESTORE_PATHS", ("/bin/sh",))
        return recorded

    def test_loopback_is_brought_up_once_with_the_first_ip_command(self, calls: list[list[str]]) -> None:
        main_sandbox._apply_netfilter(("COMMIT",))

        assert calls[0] == ["/usr/sbin/ip", "link", "set", "lo", "up"]
        assert [c for c in calls if c[1:2] == ["link"]] == [calls[0]]

    def test_the_next_ip_command_is_tried_when_one_is_missing(
        self, calls: list[list[str]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def run(cmd: list[str], **kwargs: Any) -> Any:
            calls.append(cmd)
            if cmd[0] == "/usr/sbin/ip":
                raise FileNotFoundError(cmd[0])
            return SimpleNamespace(returncode=0, stderr=b"")

        monkeypatch.setattr(main_sandbox.subprocess, "run", run)

        main_sandbox._apply_netfilter(("COMMIT",))

        assert [c[0] for c in calls if c[1:2] == ["link"]] == ["/usr/sbin/ip", "/sbin/ip"]

    def test_a_filter_killed_by_a_signal_stops_the_child(
        self, calls: list[list[str]], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def run(cmd: list[str], **kwargs: Any) -> Any:
            return SimpleNamespace(returncode=-9 if cmd[0] == "/bin/sh" else 0, stderr=b"killed")

        monkeypatch.setattr(main_sandbox.subprocess, "run", run)

        with pytest.raises(RuntimeError, match="iptables-restore failed"):
            main_sandbox._apply_netfilter(("COMMIT",))
