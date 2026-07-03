# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The complete mode: the whole server under `python-sb`, driven over MCP.

D2 of the design spec asks for both usage modes. The partial mode is covered by
test_tools_sandbox.py, which arms `sandboxes()` around the tool calls in this
process. Here the server itself is launched inside the sandbox and spoken to
over stdio by a real MCP client, so nothing in the test process is armed: the
rules can only come from the profile the launcher was given.

This is the mode the tests could not have caught the transport defects in.
`is_in_sandbox()` is true from the start, so `@sandbox` calls the inner function
directly and the SSE bridge is never used.

MCP carries text, so a refusal arrives as a message rather than an exception.
The tools name the rule themselves, which is why asserting on it here is not
asserting on a generic error path.
"""

import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

SAMPLE_ROOT = Path(__file__).parent.parent
CONFIG = "mcp_server/.py-sandboxes-complete"

ALLOWED_URL = "https://www.google.com/"
DENIED_URL = "https://example.com/"
POPEN_ESCAPE = "[c for c in ().__class__.__base__.__subclasses__() if c.__name__=='Popen'][0](['/bin/echo','pwned'])"


@pytest.fixture
def sandboxed_server() -> Client:
    """An MCP client onto a server running entirely inside the sandbox."""
    return Client(
        StdioTransport(
            command=sys.executable,
            args=[
                "-m",
                "pysandboxes.python_sb",
                f"--pysandboxes-config={CONFIG}",
                "-m",
                "mcp_server.main",
                "-t",
                "stdio",
            ],
            cwd=str(SAMPLE_ROOT),
        )
    )


async def _call(client: Client, tool: str, **arguments: object) -> str:
    """Call a tool and return what the client received, result or refusal."""
    try:
        result = await client.call_tool(tool, arguments)
        return str(getattr(result, "data", result))
    except Exception as e:  # the server reports a refusal as a tool error
        return f"ERROR {e}"


@pytest.mark.asyncio
async def test_the_tools_answer_under_python_sb(sandboxed_server: Client) -> None:
    """The server works at all in complete mode, which the rest depends on."""
    async with sandboxed_server as client:
        tools = {tool.name for tool in await client.list_tools()}
        assert {"fetch_webpage", "evaluate_expression"} <= tools, tools

        assert "14" in await _call(client, "evaluate_expression", expression="2*(3+4)")


@pytest.mark.asyncio
async def test_an_allowed_host_is_reached_under_python_sb(sandboxed_server: Client) -> None:
    async with sandboxed_server as client:
        answer = await _call(client, "fetch_webpage", url=ALLOWED_URL)

    assert not answer.startswith("ERROR"), answer
    assert answer.strip()


@pytest.mark.asyncio
async def test_a_host_outside_the_rules_is_refused_under_python_sb(
    sandboxed_server: Client,
) -> None:
    async with sandboxed_server as client:
        answer = await _call(client, "fetch_webpage", url=DENIED_URL)

    assert answer.startswith("ERROR"), answer
    assert "refused by the sandbox" in answer, answer
    assert "DENIED" in answer, answer


@pytest.mark.asyncio
async def test_the_malicious_expression_is_confined_under_python_sb(
    sandboxed_server: Client,
) -> None:
    async with sandboxed_server as client:
        answer = await _call(client, "evaluate_expression", expression=POPEN_ESCAPE)

    assert answer.startswith("ERROR"), answer
    assert "process-exec" in answer, answer
