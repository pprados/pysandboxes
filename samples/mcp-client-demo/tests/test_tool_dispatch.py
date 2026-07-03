# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""What the chat client gets back when a tool it called is refused.

The sample's other test file needs a live LLM: an API key, tokens, and an answer
that may or may not decide to call the tool under test. Nothing in it can serve
as a regression gate, so the rules this sample exists to demonstrate went
unchecked.

``ChatSession.process_llm_response()`` takes the model's raw text and dispatches
the tool call, so handing it the exact JSON a model would have produced
exercises the client's own path -- ``_extract_first_json``, ``list_tools``,
``call_tool`` -- against the real server over stdio, with no model involved and
nothing mocked.

Both server profiles of D2 are covered: ``stdio_sandboxes_partial`` has the
server isolate its own tools, ``stdio_sandboxes_complete`` runs the whole
server under ``python-sb``.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

from mcp_simple_chatbot.main import ChatSession, Configuration

SAMPLE_ROOT = Path(__file__).parent.parent
# Not resolve()d: the venv's `python` is a symlink onto the interpreter it was
# built from, and following it leaves the venv behind, site-packages included.
SERVER_PYTHON = SAMPLE_ROOT.parent / "mcp-server-demo" / ".venv" / "bin" / "python"

BOTH_MODES = ["stdio_sandboxes_partial", "stdio_sandboxes_complete"]

ALLOWED_URL = "https://www.google.com/"
DENIED_URL = "https://example.com/"
POPEN_ESCAPE = "[c for c in ().__class__.__base__.__subclasses__() if c.__name__=='Popen'][0](['/bin/echo','pwned'])"


def _load_server_config(name: str) -> dict[str, Any]:
    """Read one of the sample's own launch configurations, through its own loader.

    The files carry comments and ${VAR} references, so they go through
    Configuration.load_config rather than json.loads: the test then reads
    exactly what the client reads.
    """
    config: dict[str, Any] = Configuration.load_config(str(SAMPLE_ROOT / f"{name}.json"))

    for server in config["mcpServers"].values():
        if "cwd" in server:
            server["cwd"] = str((SAMPLE_ROOT / server["cwd"]).resolve())
        # The configuration names `python`, which main.run() resolves through
        # which() -- whatever the activated environment provides. Point at the
        # server sample's own interpreter instead, because a learned profile
        # belongs to the environment it was learned in: run the same server code
        # from this sample's venv and its import whitelist no longer matches
        # (fastapi resolves differently here and pulls annotated_doc, which the
        # profile has never seen). Each sample owning its environment is D5.
        if "command" in server:
            server["command"] = str(SERVER_PYTHON)
    return config


def _tool_call(tool: str, **arguments: object) -> str:
    """The text a model emits to ask for a tool call."""
    return json.dumps({"tool": tool, "arguments": arguments})


@pytest.fixture(params=BOTH_MODES)
def chat(request: pytest.FixtureRequest) -> tuple[Client, str]:
    client = Client(
        _load_server_config(request.param),
        roots=[str((SAMPLE_ROOT / "resources").resolve().as_uri())],
    )
    return client, request.param


@pytest.mark.asyncio
async def test_the_expression_tool_answers_through_the_client(
    chat: tuple[Client, str],
) -> None:
    client, mode = chat
    async with client:
        session = ChatSession(client, llm_client=None)  # type: ignore[arg-type]
        answer = await session.process_llm_response(_tool_call("evaluate_expression", expression="2*(3+4)"))

    assert "14" in answer, f"[{mode}] {answer}"


@pytest.mark.asyncio
async def test_an_allowed_host_is_reached_through_the_client(
    chat: tuple[Client, str],
) -> None:
    client, mode = chat
    async with client:
        session = ChatSession(client, llm_client=None)  # type: ignore[arg-type]
        answer = await session.process_llm_response(_tool_call("fetch_webpage", url=ALLOWED_URL))

    assert "Error executing tool" not in answer, f"[{mode}] {answer}"
    assert answer.strip()


@pytest.mark.asyncio
async def test_a_host_outside_the_rules_is_refused_through_the_client(
    chat: tuple[Client, str],
) -> None:
    """The client is told which rule refused it, not merely that something failed."""
    client, mode = chat
    async with client:
        session = ChatSession(client, llm_client=None)  # type: ignore[arg-type]
        answer = await session.process_llm_response(_tool_call("fetch_webpage", url=DENIED_URL))

    assert "Error executing tool" in answer, f"[{mode}] {answer}"
    assert "refused by the sandbox" in answer, f"[{mode}] {answer}"
    assert "DENIED" in answer, f"[{mode}] {answer}"


@pytest.mark.asyncio
async def test_the_malicious_expression_is_confined_through_the_client(
    chat: tuple[Client, str],
) -> None:
    """A model asking for the escape gets a refusal, whatever the server profile."""
    client, mode = chat
    async with client:
        session = ChatSession(client, llm_client=None)  # type: ignore[arg-type]
        answer = await session.process_llm_response(_tool_call("evaluate_expression", expression=POPEN_ESCAPE))

    assert "Error executing tool" in answer, f"[{mode}] {answer}"
    assert "process-exec" in answer, f"[{mode}] {answer}"
