# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`net-resolve=runtime` over IPv6 under `unshare`, `bwrap` and `gvisor`: the `AAAA` of an allowed name opens its address.

Same two layers as ``test_unshare_runtime_dns``: ``kernel`` (Python guard off, only ``ip6tables`` refuses) and
``guard`` (both layers judge). The names still travel over IPv4; only the learned address is IPv6. The host needs no
global IPv6 route: slirp4netns maps ``fd00::2`` of the sandbox to the host loopback ``::1``.
"""

import json
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pysandboxes._os_sandbox import unsupported_platform_reason

from ._env import provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parent.parent.parent


PROVIDERS = ("unshare", "bwrap", "gvisor")


def _skip_reason(provider: str) -> str | None:
    if reason := unsupported_platform_reason(provider) or provider_skip_reason(provider):
        return reason
    if tool := next(
        (t for t in ("nsenter", "iptables", "ip6tables", "ip6tables-restore") if not shutil.which(t)), None
    ):
        return f"{tool} is missing"
    try:
        socket.socket(socket.AF_INET6).bind(("::1", 0))
    except OSError:
        return "the host has no IPv6 loopback"
    return None


@pytest.fixture(scope="module", params=[(p, layer) for p in PROVIDERS for layer in ("kernel", "guard")], ids="-".join)
def outcome(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    provider, layers = request.param
    if reason := _skip_reason(provider):
        pytest.skip(reason)
    work = tmp_path_factory.mktemp("runtime_dns_ipv6")
    result = subprocess.run(
        [sys.executable, "-m", "tests.integration_tests.tst_unshare_runtime_ipv6_probe", str(work), layers, provider],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-6000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_an_ipv6_address_nobody_resolved_is_refused_even_when_the_listener_is_there(outcome: dict[str, Any]) -> None:
    assert outcome["result"]["literal_before_resolution"] == "REFUSED"


def test_the_aaaa_of_an_allowed_name_is_opened_when_the_name_resolves(outcome: dict[str, Any]) -> None:
    assert outcome["result"]["resolved"] == ["fd00::2"]
    assert outcome["result"]["allowed_port"] == "CONNECTED"
    assert outcome["questions"] >= 1


def test_the_port_of_the_name_rule_is_kept_on_the_learned_ipv6_address(outcome: dict[str, Any]) -> None:
    assert outcome["result"]["other_port"] == "REFUSED"


def test_a_name_no_rule_allows_does_not_resolve_over_ipv6(outcome: dict[str, Any]) -> None:
    assert outcome["result"]["denied_name"] == "NXDOMAIN"


def test_an_ipv6_resolver_the_program_names_itself_is_refused(outcome: dict[str, Any]) -> None:
    assert outcome["result"]["hard_coded_resolver"] == "REFUSED"


def test_the_ipv6_address_is_closed_when_its_ttl_is_over_and_opened_again_by_a_new_resolution(
    outcome: dict[str, Any],
) -> None:
    assert outcome["result"]["after_expiry"] == "REFUSED"
    assert outcome["result"]["relearned"] == "CONNECTED"


def test_the_resolver_is_gone_with_the_sandbox(outcome: dict[str, Any]) -> None:
    assert outcome["resolver_started"] is True and outcome["resolver_port_free"] is True
