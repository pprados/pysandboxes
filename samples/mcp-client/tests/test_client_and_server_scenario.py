"""
Test all the scenario with 'claude-code'
"""

import logging
import os
import re
import time
from subprocess import run, Popen, PIPE

import pytest

logger = logging.getLogger(__name__)

timeout = 30
all_mcp_client_os_sandbox = [
    # "None",
    # "Subprocess",
    "firejail",
]
all_mcp_server_config = [
    # "stdio_no_sandbox",
    # "stdio_complete_mode",
    "stdio_partial_mode",
    # "http",
]


def _start_server(mcp_server_config: str) -> Popen | None:
    process: Popen | None = None
    if mcp_server_config == "http.json":
        process = Popen(
            (
                "uv", "run",
                # "python",
                "-m", "pysandboxes.python_sb",
                "-m", "mcp_server.main", "-t", "http",
            ),
            cwd="../mcp-server",
            env=os.environ.copy() | {"OS_SANDBOX": "None"},
            stdout=PIPE, stderr=PIPE,
            text=True, shell=False,
        )
        time.sleep(0.5)
    return process


# @pytest.mark.skip(reason="To save tokens.")  # FIX_RELEASE
@pytest.mark.skipif(not os.environ.get("GROK_API_KEY"), reason="Set GROK_API_KEY")
@pytest.mark.parametrize("mcp_server_config", all_mcp_server_config)
@pytest.mark.parametrize("mcp_client_os_sandbox", all_mcp_client_os_sandbox)
def test_claude_evaluate_expression(
        mcp_client_os_sandbox: str,
        mcp_server_config: str,
) -> None:
    process: Popen | None = None
    try:
        mcp_server_config += ".json"
        process = _start_server(mcp_server_config)
        start_client = \
            (['-m', 'pysandboxes.python_sb'] +
             ['-m', 'mcp_simple_chatbot.main'])
        cmd = (
            "python",
            *start_client,
            "-c", mcp_server_config,
            "-p", "calc 2+3"
        )
        logger.info("cmd: %s", " ".join(cmd))
        result = run(
            cmd,
            env=os.environ.copy() | {"OS_SANDBOX": mcp_client_os_sandbox},
            timeout=timeout,
            input="",
            capture_output=True,
            text=True, check=True, shell=False)
        print(result.stdout)
        if result.stderr:
            print("------- STDERR")
            print(result.stderr)
        assert "5" in result.stdout
    finally:
        if process:
            process.kill()


@pytest.mark.skip(reason="To save tokens.")  # FIX_RELEASE
@pytest.mark.skipif(not os.environ.get("GROK_API_KEY"), reason="Set GROK_API_KEY")
@pytest.mark.parametrize("mcp_server_config", all_mcp_server_config)
@pytest.mark.parametrize("mcp_client_os_sandbox", all_mcp_client_os_sandbox)
def test_claude_fetch_webpage(
        mcp_client_os_sandbox: str,
        mcp_server_config: str,
) -> None:
    process: Popen | None = None
    try:
        mcp_server_config += ".json"
        process = _start_server(mcp_server_config)

        start_client = [
            '-m', 'pysandboxes.python_sb',
            '-m', 'mcp_simple_chatbot.main'
        ]
        cmd = (
            "uv", "run",
            # which("python"),
            *start_client,
            "-c", mcp_server_config,
            "-p", "get and summarize the page http://www.google.com"
        )
        logger.info("cmd: %s", " ".join(cmd))
        result = run(
            cmd,
            env=os.environ.copy() | {"OS_SANDBOX": mcp_client_os_sandbox},
            timeout=timeout,
            stdout=None, stderr=None,
            input="",
            capture_output=True,
            text=True, check=False, shell=False)  # FIXME check
        print(result.stdout)
        if result.stderr:
            print("------- STDERR")
            print(result.stderr)
        assert re.search("google.*homepage", result.stdout.lower())
        assert re.search("connection.*error", result.stdout.lower()) is None
    finally:
        if process:
            process.kill()
