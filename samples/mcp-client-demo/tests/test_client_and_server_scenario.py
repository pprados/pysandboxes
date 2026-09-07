"""
Test all the scenario with 'claude-code'
"""

import logging
import os
import re
import subprocess
from shutil import which
from subprocess import Popen, run
from typing import Optional

import pytest
from pysandboxes.remote.tools import get_bridge_interfaces

logger = logging.getLogger(__name__)

timeout = 30
all_mcp_client_os_sandbox: list[str] = [
    "None",
    "Subprocess",
]
all_mcp_server_config: list[str] = [
    "stdio_no_sandbox",
    "stdio_sandboxes_complete",
    "stdio_sandboxes_partial",
    "http",
]

# End-to-end through a live model: two tests over four server configurations,
# each spending tokens and each depending on the model choosing to call the
# tool under test. Gated on OPENAI_API_KEY alone -- set it in .env, which the
# Makefile sources before pytest.
requires_llm = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="Set OPENAI_API_KEY",
)


def _get_default_interface() -> str:
    """
    Retrieves the name of the default network interface by reading the
    /proc/net/route pseudo-file on Linux.

    Returns the interface name (str) or None if not found.
    """

    # The default route destination is represented by '00000000' in the file
    DEFAULT_DESTINATION: str = "00000000"

    # Open the file containing the routing table
    with open("/proc/net/route", "r") as f:
        # Read all lines
        content_lines: list[str] = f.readlines()

    # Iterate over lines, skipping the header (first line)
    for line in content_lines[1:]:
        # Split the line by tabs or spaces
        parts: list[str] = line.split()

        # parts[1] is the Destination column
        if len(parts) > 1 and parts[1] == DEFAULT_DESTINATION:
            # parts[0] is the Iface (Interface name) column
            interface_name: str = parts[0]
            return interface_name
    raise ValueError("Default interface not found.")


def _get_ip_from_interface(interface_name: str) -> str | None:
    try:
        # Execute the 'ip addr show [interface_name]' command
        # and capture the output.
        # check=True raises an error if the command fails.
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ["ip", "addr", "show", interface_name],
            capture_output=True,
            text=True,
            check=True,
        )

        output: str = result.stdout

        # Regex to find the IPv4 address (e.g., 192.168.1.10/24)
        # and capture the IP part before the slash.
        # 'inet' is used for IPv4 addresses.
        ip_match: Optional[re.Match[str]] = re.search(r"inet\s+([\d.]+)/", output)

        if ip_match:
            # Return the captured IP address (group 1 of the regex)
            return ip_match.group(1)
        else:
            # Interface exists but has no IPv4 address assigned
            print(f"No IPv4 address found for interface '{interface_name}'.")
            return None

    except subprocess.CalledProcessError:
        # Handle case where the interface name is invalid or the 'ip' command fails
        print(f"Error: Interface '{interface_name}' not found or 'ip' command failed.")
        return None
    except FileNotFoundError:
        # Handle case where the 'ip' command is not found (should not happen on Ubuntu)
        print("Error: The 'ip' command was not found. Is your system path correct?")
        return None


# In some scenarios, it is not possible to access localhost from an OS sandbox.
# For example, with firejail. It is necessary to use the host's IP address and enable a bridge.
# Computed on demand: at import time this runs `ip addr` on every collection,
# and _get_default_interface() raises on a host with no default route, turning a
# skipped test into a collection error.
def _my_ip() -> str | None:
    return _get_ip_from_interface(_get_default_interface())


def _start_server(mcp_server_config: str) -> Popen | None:
    process: Popen | None = None
    if mcp_server_config == "http.json":
        cmd = (
            "uv",
            "run",
            "-m",
            "pysandboxes.python_sb",
            "-m",
            "mcp_server.main",
            "-t",
            "http",
            "-p",
            "8000",
            # "--sandbox-port", "48000",
        )
        logger.debug("Run " + " ".join(cmd))
        process = Popen(
            cmd,
            cwd="../mcp-server-demo",
            env=os.environ.copy() | {"OS_SANDBOX": "None", "PY_SANDBOX": "None"},
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # stdout=None, stderr=None,
            text=True,
            shell=False,
        )
    return process


@requires_llm
@pytest.mark.parametrize("mcp_server_config", all_mcp_server_config)
@pytest.mark.parametrize("mcp_client_os_sandbox", all_mcp_client_os_sandbox)
def test_claude_evaluate_expression(
    mcp_client_os_sandbox: str,
    mcp_server_config: str,
) -> None:
    process: Popen | None = None
    try:
        mcp_server_config += ".json"

        if mcp_server_config == "http.json":
            if not get_bridge_interfaces():
                pytest.skip("Need 'bridge' interface. Use `sudo add-bridge.sh`")

        process = _start_server(mcp_server_config)
        python_executable = which("python")
        assert python_executable is not None
        start_client = ["-m", "pysandboxes.python_sb"] + ["-m", "mcp_simple_chatbot.main"]
        cmd: list[str] = [
            python_executable,
            "-u",
            *start_client,
            "-c",
            mcp_server_config,
            "-p",
            "calc 2+3",
        ]
        logger.info("cmd: %s", " ".join([repr(c) if " " in c else c for c in cmd]))
        assert not process or process.returncode is None
        my_ip = _my_ip()
        assert my_ip is not None
        result = run(
            cmd,
            env=os.environ.copy() | {"OS_SANDBOX": mcp_client_os_sandbox, "MY_IP": my_ip},
            timeout=timeout,
            input="",
            capture_output=True,  # To debug, deactivate capture_output
            check=True,
            text=True,
            shell=False,
        )
        print(result.stdout)
        if result.stderr:
            print("-------")
            print(result.stderr)
        assert "5" in result.stdout
    finally:
        if process:
            process.kill()


@requires_llm
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

        python_executable = which("python")
        assert python_executable is not None

        start_client = ["-m", "pysandboxes.python_sb", "-m", "mcp_simple_chatbot.main"]
        cmd: list[str] = [
            python_executable,
            *start_client,
            "-c",
            mcp_server_config,
            "-p",
            "get and summarize the page http://www.google.com",
        ]
        logger.info("cmd: %s", " ".join([repr(c) if " " in c else c for c in cmd]))
        assert not process or process.returncode is None
        my_ip = _my_ip()
        assert my_ip is not None
        result = run(
            cmd,
            env=os.environ.copy() | {"OS_SANDBOX": mcp_client_os_sandbox, "MY_IP": my_ip},
            timeout=timeout,
            capture_output=True,  # To debug, deactivate capture_output
            input="",
            text=True,
            check=True,
            shell=False,
        )
        print(result.stdout)
        if result.stderr:
            print("------- STDERR")
            print(result.stderr)
        assert "google" in result.stdout.lower()
        assert re.search("connection.*error", result.stdout.lower()) is None
    finally:
        if process:
            process.kill()
