# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`run_server`: how the sandbox process builds, registers and starts its SSE daemon."""

import json
import logging
import os
from typing import Any

import pytest  # type: ignore[import-untyped]

from pysandboxes import _os_sandbox
from pysandboxes.all_rules import EmptyRules
from pysandboxes.remote import main_sandbox
from pysandboxes.remote.daemon_parameters import DaemonParameters
from pysandboxes.remote.sse_server_daemon import SSEServerDaemon


def _config(*, init_fn: str = "", os_sandbox: str = "subprocess", py_sandbox: bool = True) -> DaemonParameters:
    return DaemonParameters(
        all_rules=EmptyRules._replace(os_sandbox=os_sandbox, use_py_sandbox=py_sandbox),
        log_level=logging.INFO,
        log_format="%(message)s",
        use_rich_handler=False,
        token="secret",
        port=4321,
        init_fn=init_fn,
        bind_host="0.0.0.0",
    )


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    journal: list[tuple[str, Any]] = []

    def factory(token: str, **kwargs: Any) -> SSEServerDaemon:
        journal.append(("factory", (token, kwargs)))
        return SSEServerDaemon(token, port=kwargs["port"])

    async def start(self: SSEServerDaemon, rules: Any, **kwargs: Any) -> None:
        journal.append(("start", (rules, kwargs)))

    async def join(self: SSEServerDaemon) -> None:
        journal.append(("join", None))

    def register(daemon: Any) -> None:
        journal.append(("register", daemon))

    monkeypatch.setattr(_os_sandbox, "providers_factory", {"_sse_server": factory})
    monkeypatch.setattr(_os_sandbox, "_set_current_daemon", register)
    monkeypatch.setattr(SSEServerDaemon, "_start", start)
    monkeypatch.setattr(SSEServerDaemon, "join", join)
    return journal


async def test_the_daemon_is_built_registered_started_then_joined(server: list[tuple[str, Any]]) -> None:
    config = _config()

    assert await main_sandbox.run_server(config) == 0

    assert [name for name, _ in server] == ["factory", "register", "start", "join"]
    assert server[0][1] == ("secret", {"port": 4321, "bind_host": "0.0.0.0"})
    assert isinstance(server[1][1], SSEServerDaemon)
    rules, kwargs = server[2][1]
    assert rules is config.all_rules
    assert kwargs == {"envs": os.environ, "log_level": logging.INFO, "init_fn": None}


async def test_the_init_function_is_resolved_from_its_reference(server: list[tuple[str, Any]]) -> None:
    await main_sandbox.run_server(_config(init_fn="json:dumps"))

    assert server[2][1][1]["init_fn"] is json.dumps


async def test_an_unknown_init_module_stops_the_process(server: list[tuple[str, Any]]) -> None:
    with pytest.raises(SystemExit) as stop:
        await main_sandbox.run_server(_config(init_fn="no_such_module_for_run_server:f"))

    assert stop.value.code == -1
    assert server == []


async def test_an_unknown_init_function_is_refused(server: list[tuple[str, Any]]) -> None:
    with pytest.raises(AssertionError):
        await main_sandbox.run_server(_config(init_fn="json:no_such_function"))

    assert server == []


@pytest.mark.parametrize("provider", ["subprocess", "firejail", "unshare", "landlock", "bwrap", "qemu"])
async def test_every_kernel_backed_provider_is_accepted(server: list[tuple[str, Any]], provider: str) -> None:
    assert await main_sandbox.run_server(_config(os_sandbox=provider)) == 0


@pytest.mark.parametrize("provider", ["none", "error", "docker", ""])
async def test_any_other_provider_is_refused(server: list[tuple[str, Any]], provider: str) -> None:
    with pytest.raises(AssertionError):
        await main_sandbox.run_server(_config(os_sandbox=provider))

    assert server == []


@pytest.mark.parametrize(
    ("py_sandbox", "message"),
    [(True, "py-sandbox encapsulated in an os-sandox of type 'bwrap'"), (False, "ONLY an os-sandox of type 'bwrap'")],
)
async def test_the_startup_message_says_whether_the_python_layer_is_on(
    server: list[tuple[str, Any]], caplog: pytest.LogCaptureFixture, py_sandbox: bool, message: str
) -> None:
    with caplog.at_level(logging.INFO, logger="Pysandboxes"):
        await main_sandbox.run_server(_config(os_sandbox="bwrap", py_sandbox=py_sandbox))

    assert message in caplog.text
    assert ("ONLY" in caplog.text) is (not py_sandbox)
