# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Firejail's netfilter files, the bridge choice, and the guards of the daemon call that no test reached."""

import asyncio
import ipaddress
import subprocess
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.e import SandBoxProtocolError
from pysandboxes.guard_socket import parse_rules
from pysandboxes.remote import firejail_sse_daemon
from pysandboxes.remote import qemu_sse_daemon as qemu
from pysandboxes.remote.firejail_sse_daemon import FireJailSSEDaemon
from pysandboxes.remote.sse_server_daemon import SSEServerDaemon
from pysandboxes.sb_types import ConfigLine


def _rules() -> Any:
    socket_rules, _, _ = parse_rules([ConfigLine("net=ALLOW|TCP|*|443|OUT", Path(), 0)], [])
    return EmptyRules._replace(socket_rules=tuple(socket_rules))


def _args(tmp_path: Path, bridges: list[str], *, pipe: bool = False, dns: list[Any] | None = None) -> list[str]:
    config = tmp_path / "firejail.config"
    config.write_text("restricted-network no\n", encoding="utf-8")
    with (
        patch.object(firejail_sse_daemon, "FIREJAIL_CONFIG", config),
        patch.object(firejail_sse_daemon, "which_command", return_value="/usr/bin/firejail"),
        patch.object(firejail_sse_daemon, "get_upstream_dns", return_value=dns or []),
        patch.object(firejail_sse_daemon, "get_bridge_interfaces", return_value=bridges),
    ):
        args, _ = FireJailSSEDaemon("token")._firejail_args(_rules(), {}, tmp_path / "pipe" if pipe else None, tmp_path)
    return list(args)


class TestBridgeChoice:
    def test_a_docker_bridge_wins_wherever_it_is_listed(self, tmp_path: Path) -> None:
        assert "--net=docker0" in _args(tmp_path, ["br0", "docker0", "virbr0"])

    def test_without_a_docker_bridge_the_first_one_is_taken(self, tmp_path: Path) -> None:
        assert "--net=br0" in _args(tmp_path, ["br0", "virbr0"])


class TestNetfilterFiles:
    @pytest.fixture
    def recorded(self) -> Any:
        calls: list[tuple[list[Any], bool]] = []

        def fake(rules: Any, dns: list[Any], is_ipv6: bool) -> list[str]:
            calls.append((list(dns), is_ipv6))
            return [f"ipv6={is_ipv6}"]

        with patch.object(firejail_sse_daemon, "rule_to_netfilter", fake):
            yield calls

    def test_each_file_carries_the_rules_of_its_family_and_only_the_v4_one_the_dns(
        self, tmp_path: Path, recorded: list[tuple[list[Any], bool]]
    ) -> None:
        dns = [ipaddress.IPv4Address("192.0.2.53")]

        args = _args(tmp_path, ["br0"], pipe=True, dns=dns)

        assert recorded == [(dns, False), ([], True)]
        files = {a.split("=")[0]: Path(a.split("=", 1)[1]) for a in args if a.startswith("--netfilter")}
        contents: dict[str, str] = {}

        def read(name: str) -> None:
            contents[name] = files[name].read_text()

        readers = [threading.Thread(target=read, args=(name,), daemon=True) for name in files]
        for reader in readers:
            reader.start()
        for reader in readers:
            reader.join(10)
        assert contents == {"--netfilter": "ipv6=False", "--netfilter6": "ipv6=True"}

    def test_the_publishing_threads_never_keep_the_process_alive(self, tmp_path: Path) -> None:
        created: list[dict[str, Any]] = []

        def thread(**kwargs: Any) -> MagicMock:
            created.append(kwargs)
            return MagicMock()

        with patch.object(firejail_sse_daemon.threading, "Thread", thread):
            _args(tmp_path, ["br0"], pipe=True)

        assert [kw["daemon"] for kw in created] == [True, True]


class TestCallGuard:
    @pytest.mark.parametrize(("forced", "accepting"), [(True, False), (False, True), (True, True)])
    def test_a_call_is_refused_only_when_it_is_neither_forced_nor_accepted(self, forced: bool, accepting: bool) -> None:
        daemon = SSEServerDaemon("tok", port=1234)
        daemon._accept_incoming = accepting
        daemon.max_connect_retry = 0

        async def call() -> None:
            await daemon.async_call_in_sandbox(lambda: None, forced)

        with pytest.raises(SandBoxProtocolError) as error:
            asyncio.run(call())

        assert "being stopped" not in str(error.value)


class TestLddFailures:
    @pytest.mark.parametrize(
        "failure", [OSError("no ldd"), subprocess.TimeoutExpired("ldd", 60)], ids=["missing", "timeout"]
    )
    def test_an_ldd_that_cannot_run_yields_nothing(self, failure: Exception) -> None:
        with patch.object(qemu.subprocess, "run", side_effect=failure):
            assert qemu._ldd_resolved_paths(Path("/bin/x")) == set()
