# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
import argparse
import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from fastmcp import FastMCP
from httpx_file import FileTransport
from markdownify import markdownify as md
from pysandboxes import is_in_sandbox, sandbox, sandbox_denials, sandboxes
from pysandboxes.remote.tools import set_pdeathsig

logger = logging.getLogger(__name__)

level = logging.INFO
format = "MCPServer: %(levelname)-5s [%(process)d] %(name)s: %(message)s"
logging.getLogger("Pysandboxes").setLevel(logging.INFO)
logging.getLogger("pysandboxes").setLevel(level)
logging.getLogger().setLevel(level)
# logging.getLogger("pysandboxes.remote.firejail_daemon").setLevel(level)

logging.basicConfig(
    force=True,
    level=level,
    format=format,
)

mcp = FastMCP(
    "My MCP Server",
)

RESOURCES_DIR = Path(__file__).parent.parent / "resources"


@mcp.resource("config://version")
def get_version() -> str:
    return "1.0.0"


@mcp.resource("greeting://{name}")
def greet(name: str) -> str:
    return f"Hello {name} from MCPServer!"


# Note: @mcp.resource annotation return an object, not a method.
# When importing the module into the sandbox, the function to be invoked is not
# available.
# See https://gofastmcp.com/patterns/decorating-methods
# Split the body in two part.
@mcp.resource("myresource://{path}")
async def read_file_resource(path: str) -> str:
    """Expose files from the resources directory as MCP resources."""
    return await _read_file_resource(path)


@sandbox
async def _read_file_resource(path: str) -> str:
    """Expose files from the resources directory as MCP resources in a sandbox."""
    file_path = RESOURCES_DIR / path
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not file_path.is_relative_to(RESOURCES_DIR):
        raise ValueError("Access denied: path outside resources directory")
    logger.debug(f"Reading myresource:{path}")
    return file_path.read_text()


def _explain(error: Exception) -> str:
    """Name the rule that refused the call, when one did.

    A tool reports over MCP, which carries text: whatever the caller receives is
    a string. httpx rewrites a refused connection into "All connection attempts
    failed", so without this the client cannot tell a rule from an outage --
    which is the whole point of putting the tool in a sandbox.
    """
    denials = sandbox_denials(error)
    if not denials:
        return str(error)
    return f"{error} [refused by the sandbox: {'; '.join(denials)}]"


@sandbox
async def _fetch_webpage(url: str) -> str:
    """Fetches the content of a webpage and returns it as markdown."""
    assert is_in_sandbox()
    try:
        logger.info(f"Fetching webpage: {url}")
        # For the demo, accept the 'file:' URL
        async with httpx.AsyncClient(mounts={"file://": FileTransport()}) as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            logger.info(f"Successfully fetched: {url}")
            return md(response.text)
    except Exception as e:
        raise ValueError(f"Failed to fetch webpage: {_explain(e)}")


@mcp.tool(
    name="fetch_webpage",
    description="Fetches the content of a webpage from a given URL",
)
async def fetch_webpage(url: str) -> str:
    return await _fetch_webpage(url)


# Define the calculator tool
@sandbox
async def _evaluate_expression(expression: str) -> float:
    """Evaluates a mathematical expression and returns the result."""
    assert is_in_sandbox()
    try:
        # Warning: eval() is unsafe for untrusted input;
        # use a proper parser in production
        logger.info(f"Calculated : {expression}")

        result = eval(
            expression,
            {"__builtins__": {}},
            {},
        )
        logger.info(f"Result : {result}")
        return result
    except Exception as e:
        raise ValueError(f"Invalid expression: {_explain(e)}")


@mcp.tool(
    name="evaluate_expression",
    description="Evaluates a mathematical expression and returns the result",
)
async def evaluate_expression(expression: str) -> float:
    return await _evaluate_expression(expression)


@mcp.prompt()
def analyze_data(expression: str) -> str:
    """Calculate expression."""
    return f"with evaluate_expression calcul: {expression}"


@mcp.prompt()
def summarize_webpage(url: str) -> str:
    """Summarize a webpage content."""
    return f"""Please fetch and summarize the webpage at {url}.
Use the fetch_webpage tool to get the content, then provide a concise summary."""


def run_mcp_server(
    py_sandbox: str,
    os_sandbox: str,
    transport: str,
    port: int | None,
    sandbox_port: int,
    pysandboxes_config: Path,
    **kwargs: Any,
) -> int:
    with sandboxes(
        sandboxes_config=pysandboxes_config,
        py_sandbox=py_sandbox,  # type: ignore[arg-type]
        os_sandbox=os_sandbox,  # type: ignore[arg-type]
        port=sandbox_port,
        **kwargs,
    ):
        add_parameters: dict[str, Any] = {}
        if transport == "http":
            add_parameters = {"host": "0.0.0.0", "port": port}
        mcp.run(
            transport=transport,
            show_banner=False,
            log_level=logging.getLevelName(logger.getEffectiveLevel()),
            **add_parameters,
        )
    return 0


def main() -> int:
    set_pdeathsig()
    parser = argparse.ArgumentParser(
        prog="mcp_server",
        description="Run a MCP-server",
    )
    parser.add_argument(
        "-t",
        "--transport",
        dest="transport",
        type=str,
        required=False,
        default="stdio",
        help="The transport type (e.g., http, stdio).",
    )
    parser.add_argument(
        "-p",
        "--port",
        dest="port",
        type=int,
        required=False,
        default=8000,
        help="The listened port",
    )
    parser.add_argument(
        "--sandbox-port",
        dest="sandbox_port",
        type=int,
        required=False,
        default=os.environ.get("SANDBOX_PORT", 48000),
        help="The port use for the sandbox communication",
    )
    parser.add_argument(
        "--pysandboxes-config",
        dest="config_path",
        type=Path,
        default=None,  # Use None as default value for clear checking
        help="Path to the pysandboxes configuration file.",
    )
    parser.add_argument(
        "--os-sandbox",
        dest="os_sandbox",
        type=str,
        default=os.environ.get("OS_SANDBOX", "subprocess"),
        help="Choice the os-sandbox provider.",
    )
    parser.add_argument(
        "--py-sandbox",
        dest="py_sandbox",
        type=str,
        default=os.environ.get(
            "PY_SANDBOX", "True"
        ),  # Use None as default value for clear checking
        help="Choice to activate the py-sandbox.",
    )
    parser.add_argument(
        "--learn",
        dest="learn",
        type=str,
        default=None,  # Use None as default value for clear checking
        help="The learning path.",
    )
    args = parser.parse_args()
    if not args.config_path:
        resource_path = importlib.resources.files(__package__)
        args.config_path = resource_path / ".py-sandboxes"

    kwargs = {}
    if args.learn:
        kwargs = {"learn": args.learn}
    logger.info(
        f"Start mcp_server with {args.transport} {args.config_path} {args.py_sandbox} {args.os_sandbox}"
    )
    return run_mcp_server(
        py_sandbox=args.py_sandbox,
        os_sandbox=args.os_sandbox,
        transport=args.transport,
        port=args.port,
        sandbox_port=args.sandbox_port,
        pysandboxes_config=args.config_path,
        **kwargs,
    )


# Run the mcp over stdio
if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("KeyboardInterrupt", file=sys.stderr)
        pass
    except SystemExit:
        pass
