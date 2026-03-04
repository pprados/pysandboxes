"""
Test all the scenario with 'claude-code'
"""

import logging
import os
import re
import subprocess
import time
from pathlib import Path
from subprocess import run, Popen, PIPE
from typing import Optional

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
    # "stdio_sandboxes_complete",
    # "stdio_sandboxes_partial",
    "http",
]


def _get_default_interface() -> str | None:
    """
    Retrieves the name of the default network interface by reading the
    /proc/net/route pseudo-file on Linux.

    Returns the interface name (str) or None if not found.
    """

    # The default route destination is represented by '00000000' in the file
    DEFAULT_DESTINATION: str = '00000000'

    try:
        # Open the file containing the routing table
        with open('/proc/net/route', 'r') as f:
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

    except FileNotFoundError:
        # If the system is not Linux or the file is missing
        print("Erreur: Le fichier /proc/net/route n'existe pas ou n'est pas accessible.")
        return None
    except Exception as e:
        print(f"Une erreur inattendue est survenue lors de la lecture de la route par défaut: {e}")
        return None

    return None


def _get_ip_from_interface(interface_name: str) -> str | None:
    try:
        # Execute the 'ip addr show [interface_name]' command
        # and capture the output.
        # check=True raises an error if the command fails.
        result: subprocess.CompletedProcess[str] = subprocess.run(
            ['ip', 'addr', 'show', interface_name],
            capture_output=True,
            text=True,
            check=True
        )

        output: str = result.stdout

        # Regex to find the IPv4 address (e.g., 192.168.1.10/24)
        # and capture the IP part before the slash.
        # 'inet' is used for IPv4 addresses.
        ip_match: Optional[re.Match[str]] = re.search(
            r'inet\s+([\d.]+)/', output
        )

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
MY_IP = _get_ip_from_interface(_get_default_interface())


def _start_server(mcp_server_config: str) -> Popen | None:
    process: Popen | None = None
    if mcp_server_config == "http.json":
        cmd = (
            "uv", "run",
            # "python",
            "-m", "pysandboxes.python_sb",
            "-m", "mcp_server.main",
            "-t", "http",
            "-p", "8000",
            # "--sandbox-port", "48000",
        )
        logger.debug("Run " + " ".join(cmd))
        process = Popen(
            cmd,
            cwd="../mcp-server",
            env=os.environ.copy() | {"OS_SANDBOX": "None", "PY_SANDBOX": "None"},
            stdout=PIPE, stderr=PIPE,
            # stdout=None, stderr=None,
            text=True, shell=False,
        )
        time.sleep(1)
    return process

# TODO: mock du LLM
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

        if mcp_server_config == "http.json":
            br0 = Path("/sys/class/net/br0")  # FIXME: check bridge
            if not br0.is_dir():
                pytest.skip(f"Need 'br0'. Use `sudo add-bridge.sh`")

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
            env=os.environ.copy() | {"OS_SANDBOX": mcp_client_os_sandbox, "MY_IP": MY_IP},
            timeout=timeout,
            input="",
            capture_output=True, check=True,
            # capture_output=False, check=False,
            text=True, shell=False)
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
