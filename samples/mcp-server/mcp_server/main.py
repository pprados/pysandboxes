import argparse
import logging
import sys
from operator import add, mul, sub, truediv
from pathlib import Path

import httpx
from fastmcp import FastMCP
from markdownify import markdownify as md

from pysandboxes import sandbox, sandboxes

logger = logging.getLogger(__name__)

level = logging.DEBUG
format = "%(levelname)-5s [%(process)d] %(name)s: %(message)s"
logging.getLogger("Pysandboxes").setLevel(logging.INFO)
logging.getLogger("pysandboxes").setLevel(level)
# logging.getLogger("pysandboxes.remote.firejail_daemon").setLevel(level)

logging.basicConfig(
    force=True,
    level=level,
    format=format,
)

mcp = FastMCP(
    "My MCP Server",
    host="127.0.0.1",
    port=8000,
    log_level=logging.getLevelName(logger.getEffectiveLevel()),
)

RESOURCES_DIR = Path(__file__).parent.parent / "resources"


# Define the calculator tool
@sandbox
@mcp.tool(
    name="evaluate_expression",
    description="Evaluates a mathematical expression and returns the result",
)
async def evaluate_expression(expression: str) -> float:
    """Evaluates a mathematical expression and returns the result."""
    try:
        # Warning: eval() is unsafe for untrusted input; use a proper parser in production
        logger.info(f"Calculated : {expression}")

        result = eval(
            expression,
            {"__builtins__": {}},
            {"add": add, "sub": sub, "mul": mul, "truediv": truediv},
        )
        logger.info(f"Result : {result}")
        return result
    except Exception as e:
        raise ValueError(f"Invalid expression: {e}")


@mcp.resource("file://{path}")
async def read_file_resource(path: str) -> str:
    """Expose files from the resources directory as MCP resources."""
    file_path = RESOURCES_DIR / path
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not file_path.is_relative_to(RESOURCES_DIR):
        raise ValueError(f"Access denied: path outside resources directory")
    logger.info(f"Reading resource: {path}")
    return file_path.read_text()


@sandbox
@mcp.tool(
    name="fetch_webpage",
    description="Fetches the content of a webpage from a given URL",
)
async def fetch_webpage(url: str) -> str:
    """Fetches the content of a webpage and returns it as markdown."""
    try:
        logger.info(f"Fetching webpage: {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()
            logger.info(f"Successfully fetched: {url}")
            return md(response.text)
    except Exception as e:
        raise ValueError(f"Failed to fetch webpage: {e}")

@mcp.prompt
def analyze_data(data_points: list[float]) -> str:
    """Creates a prompt asking for analysis of numerical data."""
    formatted_data = ", ".join(str(point) for point in data_points)
    return f"Please analyze these data points: {formatted_data}"

def run_mcp_server(
    os_sandbox: str,
    transport: str,
    sandboxes_config: Path,
    **kwargs,
) -> int:  # FIXME: mixer avec main lorsque __main__ sera réglé
    try:
        if True:  # FIXME
            # with sandboxes(
            #     sandboxes_config=sandboxes_config,
            #     os_sandbox=os_sandbox,  # type: ignore[arg-type]
            #     **kwargs,
            # ):
            mcp.run(transport=transport,
                    show_banner=False,
                    host="0.0.0.0",  # Bind to all interfaces
                    port=8000,  # Custom port
                    log_level="DEBUG",  # Override global log level
                    )  # type: ignore[arg-type]
    except KeyboardInterrupt:
        logger.info("Keyboard Interrupt")
        pass
    return 0


def main() -> int:
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
        default="subprocess",  # Use None as default value for clear checking
        help="Choice the os-sandbox provider.",
    )
    parser.add_argument(
        "--learn",
        dest="learn",
        type=str,
        default=None,  # Use None as default value for clear checking
        help="The learning path.",
    )
    args = parser.parse_args()
    kwargs = {}
    if args.learn:
        kwargs = {"learn": args.learn}
    logger.info(f"Start mcp_server with {args}")
    return run_mcp_server(args.os_sandbox, args.transport, args.config_path, **kwargs)


# Run the mcp over stdio
if __name__ == "__main__":  # FIXME: resoudre le __main__
    sys.exit(main())
