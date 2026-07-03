"""
Test all the scenario with 'claude-code'
"""

import logging
import os
import re
from shutil import which
from subprocess import PIPE, Popen, run
from time import sleep
from typing import Any

import pytest

logger = logging.getLogger(__name__)

MOCK = False  # FIX_RELEASE
if MOCK:
    from dataclasses import dataclass

    @dataclass
    class MockRunResult:
        stdout: str = ""
        stderr: str = ""

    def _mock_run(
        *openargs: Any,
        input: Any = None,
        capture_output: bool = False,
        timeout: Any = None,
        check: bool = False,
        **kwargs: Any,
    ) -> Any:
        if isinstance(openargs[0], tuple):
            cmd_line = " ".join(openargs[0])
            if "@config://version" in cmd_line:
                return MockRunResult(stdout="1.0.0.0")
            elif "http://www.google.com" in cmd_line:
                return MockRunResult(stdout="The Google homepage is")
            elif "/mcp_demo:analyze_data" in cmd_line:
                return MockRunResult(stdout="113567")
            elif "use evaluate_expression" in cmd_line:
                return MockRunResult(stdout="113567")
        return ""

    run = _mock_run

timeout = 30
all_pysandboxes_mode = ["complete", "partial"]
all_protocol = ["stdio", "http"]
all_os_sandbox = [
    "None",
    "Subprocess",
    "firejail",
]

# End-to-end through the real `claude` binary: four tests over two modes, two
# protocols and three providers, each with its own 30s budget, and each one
# spends tokens. Useful to run by hand, wrong as a regression gate -- it is what
# made `make sample-tests` hang. Opt in explicitly.
requires_claude_cli = pytest.mark.skipif(
    not os.environ.get("RUN_CLAUDE_TESTS"),
    reason="drives the real claude CLI and spends tokens; set RUN_CLAUDE_TESTS=1",
)


def _init_mcp_server(protocol: str, os_sandbox: str, pysandboxes_mode: str) -> Popen | None:
    process: Popen | None = None
    logger.info(f"init claude with {protocol=}, {os_sandbox=}, {pysandboxes_mode=}")
    run(
        "claude mcp remove mcp_demo",
        capture_output=True,
        text=True,
        check=False,
        shell=True,
    )
    if protocol == "stdio":
        if pysandboxes_mode == "complete":
            # Start the MCP server with python-sb
            run(
                "claude mcp add mcp_demo -- " "uv run -m pysandboxes.python_sb -m mcp_server.main -t stdio",
                capture_output=True,
                text=True,
                check=True,
                shell=True,
            )
        elif pysandboxes_mode == "partial":
            run(
                "claude mcp add mcp_demo -- uv run -m mcp_server.main -t stdio",
                capture_output=True,
                text=True,
                check=True,
                shell=True,
            )
    elif protocol == "http":
        # Start the MCP server with python-sb
        run(
            "claude mcp add --transport http mcp_demo http://localhost:8000/mcp",
            capture_output=True,
            text=True,
            check=True,
            shell=True,
        )
        if pysandboxes_mode == "complete":
            process = Popen(
                "uv run -m pysandboxes.python_sb -m mcp_server.main -t http",
                env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
                # stdout=PIPE,
                # stderr=PIPE,
                text=True,
                shell=True,
            )
            sleep(1)
        elif pysandboxes_mode == "partial":
            process = Popen(
                "uv run -m mcp_server.main -t http",
                env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
                stdout=PIPE,
                stderr=PIPE,
                text=True,
                shell=True,
            )
            sleep(1)
    return process


# @pytest.mark.skip(reason="To save tokens.")  # FIX_RELEASE
@requires_claude_cli
@pytest.mark.skipif(not which("claude"), reason="Install claude")
@pytest.mark.parametrize("os_sandbox", all_os_sandbox)
@pytest.mark.parametrize("protocol", all_protocol)
@pytest.mark.parametrize("mode", all_pysandboxes_mode)
def test_claude_resource_version(protocol: str, os_sandbox: str, mode: str) -> None:
    process = _init_mcp_server(protocol, os_sandbox, mode)
    try:
        cmd = (
            "claude",
            "--debug",
            "--verbose",
            "--permission-mode",
            "bypassPermissions",
            "-p",
            "call the mcp server 'mcp_demo' to print the resource @config://version",
        )
        logger.info("cmd: %s", " ".join([repr(x) if " " in x else x for x in cmd]))
        result = run(
            cmd,
            env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
            timeout=timeout,
            input="",
            capture_output=True,
            text=True,
            check=True,
            shell=False,
        )
        print(result.stdout)
        if result.stderr:
            print("------- STDERR")
            print(result.stderr)
        assert "1.0.0" in result.stdout
    finally:
        if process:
            process.terminate()


# @pytest.mark.skip(reason="To save tokens.")  # FIX_RELEASE
@requires_claude_cli
@pytest.mark.skipif(not which("claude"), reason="Install claude")
@pytest.mark.parametrize("os_sandbox", all_os_sandbox)
@pytest.mark.parametrize("protocol", all_protocol)
@pytest.mark.parametrize("mode", all_pysandboxes_mode)
def test_claude_fetch_webpage(protocol: str, os_sandbox: str, mode: str) -> None:
    process = _init_mcp_server(protocol, os_sandbox, mode)
    try:

        cmd = (
            "claude",
            "-d",
            "--verbose",
            "--permission-mode",
            "bypassPermissions",
            "--allowedTools",
            "mcp__mcp_demo__fetch_webpage",
            "-p",
            "get and summarize the page http://www.google.com",
        )
        result = run(
            cmd,
            env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
            input="",
            timeout=timeout,
            capture_output=True,
            text=True,
            check=True,
        )
        print(result.stdout)
        if result.stderr:
            print("------- STDERR")
            print(result.stderr)
        assert re.search("google.*homepage", result.stdout.lower())
    finally:
        if process:
            process.terminate()


# @pytest.mark.skip(reason="To save tokens.")  # FIX_RELEASE
@requires_claude_cli
@pytest.mark.skipif(not which("claude"), reason="Install claude")
@pytest.mark.parametrize("os_sandbox", all_os_sandbox)
@pytest.mark.parametrize("protocol", all_protocol)
@pytest.mark.parametrize("mode", all_pysandboxes_mode)
def test_claude_prompt(protocol: str, os_sandbox: str, mode: str) -> None:
    process = _init_mcp_server(protocol, os_sandbox, mode)
    try:

        cmd = (
            "claude",
            "--debug",
            "--verbose",
            "--allowedTools",
            "mcp__mcp_demo__evaluate_expression",
            "-p",
            "/mcp_demo:analyze_data (MCP) 112134+1433",
        )
        result = run(
            cmd,
            env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
            input="",
            timeout=timeout,
            capture_output=True,
            text=True,
            check=False,
        )
        print(result.stdout)
        if result.stderr:
            print("------- STDERR")
            print(result.stderr)
        assert bool(re.search(r"113[ ,.]?567", result.stdout))
    finally:
        if process:
            process.terminate()


# @pytest.mark.skip(reason="To save tokens.")  # FIX_RELEASE
@requires_claude_cli
@pytest.mark.skipif(not which("claude"), reason="Install claude")
@pytest.mark.parametrize("os_sandbox", all_os_sandbox)
@pytest.mark.parametrize("protocol", all_protocol)
@pytest.mark.parametrize("mode", all_pysandboxes_mode)
def test_claude_evaluate_expression(protocol: str, os_sandbox: str, mode: str) -> None:
    process = _init_mcp_server(protocol, os_sandbox, mode)
    try:

        cmd = (
            "claude",
            "--debug",
            "--verbose",
            # "--permission-mode", "bypassPermissions",
            "--allowedTools",
            "mcp__mcp_demo__evaluate_expression",
            "-p",
            "use evaluate_expression to calc 112134+1433",
        )
        result = run(
            cmd,
            input="",
            timeout=timeout,
            env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
            capture_output=True,
            text=True,
            check=True,
            shell=False,
        )
        print(result.stdout)
        if result.stderr:
            print("------- STDERR")
            print(result.stderr)
        assert bool(re.search(r"113[ ,.]?567", result.stdout))
    finally:
        if process:
            process.terminate()
