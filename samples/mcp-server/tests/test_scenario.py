import logging
import os
import subprocess
from shutil import which

import pytest

logger = logging.getLogger(__name__)

timeout = 60
all_os_sandbox = [
    "None",
    "Subprocess"
]
all_protocol = [
    "stdio",
    "http"
]
all_pysandboxes_mode = [
    "complete",
    "partial"
]


def _init_mcp_server(protocol: str,
                     os_sandbox: str,
                     pysandboxes_mode: str) -> subprocess.Popen | None:
    process: subprocess.Popen | None = None
    logger.info(f"init claude with {protocol=}, {os_sandbox=}, {pysandboxes_mode=}")
    subprocess.run("claude mcp remove mcp_demo",
                   capture_output=True, text=True, check=False, shell=True)
    if protocol == "stdio":
        if pysandboxes_mode == "complete":
            # Start the MCP server with python-sb
            subprocess.run("claude mcp add mcp_demo -- "
                           f"uv run -m pysandboxes.python_sb -m mcp_server.main -t stdio",
                           capture_output=True, text=True, check=True, shell=True)
        elif pysandboxes_mode == "partial":
            subprocess.run("claude mcp add mcp_demo -- "
                           f"uv run -m mcp_server.main -t stdio",
                           capture_output=True, text=True, check=True, shell=True)
    elif protocol == "http":
        # Start the MCP server with python-sb
        subprocess.run(f"claude mcp add --transport http mcp_demo http://localhost:8000/mcp",
                       capture_output=True, text=True, check=True, shell=True)
        if pysandboxes_mode == "complete":
            process = subprocess.Popen(
                f"uv run "
                f"-m pysandboxes.python_sb "
                f"-m mcp_server.main -t http",
                env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True,
            )
        elif pysandboxes_mode == "partial":
            process = subprocess.Popen(
                f"uv run -m mcp_server.main -t http",
                env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True,
            )
        # TODO: start server
        pass
    return process


@pytest.mark.skipif(not which("claude"), reason="Install claude")
@pytest.mark.parametrize("os_sandbox", all_os_sandbox)
@pytest.mark.parametrize("protocol", all_protocol)
@pytest.mark.parametrize("mode", all_pysandboxes_mode)
def test_claude_resource_version(protocol: str, os_sandbox: str, mode: str) -> None:
    process = _init_mcp_server(protocol, os_sandbox, mode)
    try:
        cmd = ("claude",
               "--debug", "--verbose",
               "--permission-mode", "bypassPermissions",
               "-p", 'call the mcp server \'mcp_demo\' to print the resource @config://version',
               )
        logger.info("cmd: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
            timeout=timeout,
            input="",
            capture_output=True, text=True, check=True, shell=False)
        print(result.stdout)
        if result.stderr:
            print("------- STDERR")
            print(result.stderr)
        assert "1.0.0" in result.stdout
    finally:
        if process:
            process.terminate()


@pytest.mark.skipif(not which("claude"), reason="Install claude")
@pytest.mark.parametrize("os_sandbox", all_os_sandbox)
@pytest.mark.parametrize("protocol", all_protocol)
@pytest.mark.parametrize("mode", all_pysandboxes_mode)
def test_claude_fetch_webpage(protocol: str, os_sandbox: str, mode: str) -> None:
    process = _init_mcp_server(protocol, os_sandbox, mode)
    try:

        cmd = ("claude",
               "--debug", "--verbose",
               "--permission-mode", "bypassPermissions",
               "-p", 'get and summarize the page http://www.google.com',
               )
        result = subprocess.run(
            cmd,
            env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
            capture_output=True, text=True, check=True, shell=True)
        print(result.stdout)
        if result.stderr:
            print("------- STDERR")
            print(result.stderr)
        assert "The Google homepage is" in result.stdout
    finally:
        if process:
            process.terminate()


@pytest.mark.skipif(not which("claude"), reason="Install claude")
@pytest.mark.parametrize("os_sandbox", all_os_sandbox)
@pytest.mark.parametrize("protocol", all_protocol)
@pytest.mark.parametrize("mode", all_pysandboxes_mode)
def test_claude_prompt(protocol: str, os_sandbox: str, mode: str) -> None:
    process = _init_mcp_server(protocol, os_sandbox, mode)
    try:

        cmd = ("claude",
               "--debug", "--verbose",
               "--permission-mode", "bypassPermissions",
               "-p", '/mcp_demo:analyze_data (MCP) 112134+1433',
               )
        result = subprocess.run(
            cmd,
            env=os.environ.copy() | {"OS_SANDBOX": os_sandbox},
            capture_output=True, text=True, check=True, shell=True)
        print(result.stdout)
        if result.stderr:
            print("------- STDERR")
            print(result.stderr)
        assert "113567" in result.stdout
    finally:
        if process:
            process.terminate()
