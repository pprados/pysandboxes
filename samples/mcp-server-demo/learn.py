# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
r"""Relearn the sample's profiles, one per mode.

Each mode has its own profile, and each is learned in its own mode. Sharing a
single file would grant each mode the other's privileges for nothing, which is
the opposite of what the partial mode is for.

    # partial: only the tool bodies enter the sandbox
    .venv/bin/python learn.py

    # complete: the whole server runs under python-sb
    .venv/bin/python -m pysandboxes.python_sb \
        --pysandboxes-config=mcp_server/.py-sandboxes-complete \
        --learn=mcp_server/.py-sandboxes-complete learn.py

Learning only ever adds, and it only writes when it observed something the
profile did not already allow -- a run that needs nothing new leaves the file
alone and prints nothing. To shrink a profile, trim it by hand down to its
header and its `net=` rules, then relearn.

Two things learning cannot produce, and that the profiles carry by hand:

- the `net=` rules -- which hosts a tool may reach is the author's decision,
  not an observation;
- the `net=...|IN` transport ports of the partial mode -- that is the sandbox
  talking to its parent, not the application reaching out.

The tools are driven through FastMCP's in-memory client so that the dispatch
observed is the real one and the process still exits cleanly: a stdio client
kills the server with SIGTERM, and the rules are then never written.

`python-sb` runs this file as a string, and the module globals a coroutine sees
are not the ones the top level bound: what a coroutine needs it has to import
itself.
"""

import asyncio
from pathlib import Path

from pysandboxes import is_in_sandbox, sandboxes

PARTIAL = Path(__file__).parent / "mcp_server" / ".py-sandboxes"


async def drive() -> None:
    from fastmcp import Client

    from mcp_server.main import mcp

    async with Client(mcp) as client:
        print(sorted(tool.name for tool in await client.list_tools()))
        print(await client.call_tool("evaluate_expression", {"expression": "2*(3+4)"}))
        page = await client.call_tool("fetch_webpage", {"url": "https://www.google.com/"})
        print(str(getattr(page, "data", page))[:80])


if is_in_sandbox():  # complete mode: python-sb already armed the profile
    asyncio.run(drive())
else:
    with sandboxes(sandboxes_config=PARTIAL, learn=str(PARTIAL)):
        asyncio.run(drive())
