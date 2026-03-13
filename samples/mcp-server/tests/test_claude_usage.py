"""
Test all the scenario with 'claude-code'
"""

import logging
import os
import re
from shutil import which
from subprocess import Popen, run, PIPE

import pytest

logger = logging.getLogger(__name__)

MOCK = False
if MOCK:
    from dataclasses import dataclass

    @dataclass
    class MockRunResult:
        stdout: str = ""
        stderr: str = ""

    def _mock_run(
        *openargs, input=None, capture_output=False, timeout=None, check=False, **kwargs
    ):
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
all_os_sandbox = [
    "None",  # FIX_RELEASE
    "Subprocess",
    "firejail",
]
all_protocol = [
    "stdio",
    "http"
]
all_pysandboxes_mode = [
    "complete",
    "partial"
]


def _init_mcp_server(
    protocol: str, os_sandbox: str, pysandboxes_mode: str
) -> Popen | None:
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
                "claude mcp add mcp_demo -- "
                f"uv run -m pysandboxes.python_sb -m mcp_server.main -t stdio",
                capture_output=True,
                text=True,
                check=True,
                shell=True,
            )
        elif pysandboxes_mode == "partial":
            run(
                "claude mcp add mcp_demo -- " f"uv run -m mcp_server.main -t stdio",
                capture_output=True,
                text=True,
                check=True,
                shell=True,
            )
    elif protocol == "http":
        # Start the MCP server with python-sb
        run(
            f"claude mcp add --transport http mcp_demo http://localhost:8000/mcp",
            capture_output=True,
            text=True,
            check=True,
            shell=True,
        )
        if pysandboxes_mode == "complete":
            process = Popen(
                f"uv run " f"-m pysandboxes.python_sb " f"-m mcp_server.main -t http",
                env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
                stdout=PIPE,
                stderr=PIPE,
                text=True,
                shell=True,
            )
        elif pysandboxes_mode == "partial":
            process = Popen(
                f"uv run -m mcp_server.main -t http",
                env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
                stdout=PIPE,
                stderr=PIPE,
                text=True,
                shell=True,
            )
    return process


@pytest.mark.skip(reason="To save tokens.")  # FIX_RELEASE
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


@pytest.mark.skip(reason="To save tokens.")  # FIX_RELEASE
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


@pytest.mark.skip(reason="To save tokens.")  # FIX_RELEASE
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
        assert "113567" in result.stdout
    finally:
        if process:
            process.terminate()


@pytest.mark.skip(reason="To save tokens.")  # FIX_RELEASE
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
        assert "113567" in result.stdout
    finally:
        if process:
            process.terminate()
