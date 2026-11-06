# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""`net-resolve=runtime` under `unshare`, `bwrap` and `gvisor`: an allowed name opens its address until the TTL.

Each scenario runs twice. In ``kernel`` the Python socket guard is disarmed (``py-sandbox=false``), so only the
firewall of the sandbox can refuse. In ``guard`` both layers judge, which proves the guard of the sandboxed process
learns the same addresses. One run of the probe covers a whole scenario, because a sandbox takes seconds to start and
the expiry needs the TTL to pass.
"""

import json
import shutil
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
    return (
        unsupported_platform_reason(provider)
        or provider_skip_reason(provider)
        or next((f"{tool} is missing" for tool in ("nsenter", "iptables") if shutil.which(tool) is None), None)
    )


@pytest.fixture(scope="module", params=PROVIDERS)
def provider(request: pytest.FixtureRequest) -> str:
    if reason := _skip_reason(str(request.param)):
        pytest.skip(reason)
    return str(request.param)


@pytest.fixture(scope="module", params=("kernel", "guard"))
def layers(request: pytest.FixtureRequest) -> str:
    """``kernel``: the Python guard is off, only the firewall refuses. ``guard``: both layers judge."""
    return str(request.param)


@pytest.fixture(scope="module")
def outcome(tmp_path_factory: pytest.TempPathFactory, layers: str, provider: str) -> dict[str, Any]:
    work = tmp_path_factory.mktemp("runtime_dns")
    result = subprocess.run(
        [sys.executable, "-m", "tests.integration_tests.tst_unshare_runtime_probe", str(work), layers, provider],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


def _json_lines(stdout: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]


@pytest.fixture(scope="module")
def one_shot(tmp_path_factory: pytest.TempPathFactory, provider: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The ``python-sb -c`` entry point: the line the sandbox printed, then the one the probe printed."""
    work = tmp_path_factory.mktemp("runtime_dns_one_shot")
    result = subprocess.run(
        [sys.executable, "-m", "tests.integration_tests.tst_unshare_runtime_probe", str(work), "python-sb", provider],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    sandbox_line, probe_line = _json_lines(result.stdout)[-2:]
    return sandbox_line, probe_line


def test_the_resolver_of_a_daemon_run_is_gone_with_the_sandbox(outcome: dict[str, Any]) -> None:
    assert outcome["resolver_started"] is True and outcome["resolver_port_free"] is True


def test_a_one_shot_python_sb_run_opens_the_address_of_an_allowed_name(
    one_shot: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    seen, probe = one_shot

    assert probe["exit_code"] == 0 and probe["questions"] >= 1
    assert seen["literal_before_resolution"] == "REFUSED"
    assert seen["resolved"] == ["10.0.2.2"] and seen["allowed_port"] == "CONNECTED"
    assert seen["other_port"] == "REFUSED"


def test_a_one_shot_python_sb_run_leaves_no_resolver_behind(
    one_shot: tuple[dict[str, Any], dict[str, Any]],
) -> None:
    assert one_shot[1]["resolver_started"] is True and one_shot[1]["resolver_port_free"] is True


def test_an_address_nobody_resolved_is_refused_even_when_the_listener_is_there(outcome: dict[str, Any]) -> None:
    assert outcome["result"]["literal_before_resolution"] == "REFUSED"


def test_the_address_of_an_allowed_name_is_opened_when_the_name_resolves(outcome: dict[str, Any]) -> None:
    assert outcome["result"]["resolved"] == ["10.0.2.2"]
    assert outcome["result"]["allowed_port"] == "CONNECTED"
    assert outcome["questions"] >= 1


def test_the_port_of_the_name_rule_is_kept_on_the_learned_address(outcome: dict[str, Any]) -> None:
    assert outcome["result"]["other_port"] == "REFUSED"


def test_a_name_no_rule_allows_does_not_resolve(outcome: dict[str, Any]) -> None:
    # With the guard armed too: in runtime mode it leaves the judgement of a name to the filtering resolver.
    assert outcome["result"]["denied_name"] == "NXDOMAIN"


def test_a_resolver_the_program_names_itself_is_refused(outcome: dict[str, Any]) -> None:
    assert outcome["result"]["hard_coded_resolver"] == "REFUSED"


def test_the_address_is_closed_when_its_ttl_is_over(outcome: dict[str, Any]) -> None:
    assert outcome["result"]["after_expiry"] == "REFUSED"


def test_a_new_resolution_opens_it_again(outcome: dict[str, Any]) -> None:
    assert outcome["result"]["relearned"] == "CONNECTED"
