import argparse
import logging
import sys
from operator import add, sub, mul, truediv
from pathlib import Path

from mcp.server.fastmcp import FastMCP, Context

from pysandboxes import sandbox, sandboxes

logger = logging.getLogger(__name__)

level = logging.INFO
format = "%(levelname)-5s [%(process)d] %(name)s: %(message)s"
logging.getLogger("Pysandboxes").setLevel(level)
logging.getLogger("pysandboxes").setLevel(level)
logging.getLogger("pysandboxes.remote.firejail_daemon").setLevel(level)

logging.basicConfig(
    force=True,
    level=level,
    format=format,
)

mcp = FastMCP("My Calculator Server",
              host="127.0.0.1",
              port=8000,
              log_level=logging.getLevelName(logger.getEffectiveLevel())
              # type: ignore[arg-type]
              )


# Define the calculator tool
@sandbox
@mcp.tool(name="evaluate_expression",
          description="Evaluates a mathematical expression and returns the result"
          )
async def evaluate_expression(expression: str) -> float:
    """Evaluates a mathematical expression and returns the result."""
    try:
        # Warning: eval() is unsafe for untrusted input; use a proper parser in production
        logger.info(f"Calculated : {expression}")

        result = eval(expression, {"__builtins__": {}},
                      {"add": add, "sub": sub, "mul": mul, "truediv": truediv})
        logger.info(f"Result : {result}")
        return result
    except Exception as e:
        raise ValueError(f"Invalid expression: {e}")


def run_mcp_server(
        os_sandbox: str,
        transport: str,
        sandboxes_config: Path,
        **kwargs,
) -> int:  # FIXME: mixer avec main lorsque __main__ sera réglé
    try:
        with sandboxes(
                sandboxes_config=sandboxes_config,
                os_sandbox=os_sandbox,  # type: ignore[arg-type]
                **kwargs,
        ):
            mcp.run(transport=transport)  # type: ignore[arg-type]
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
        help="The transport type (e.g., http, stdio)."
    )
    parser.add_argument(
        "--pysandboxes-config",
        dest="config_path",
        type=Path,
        default=None,  # Use None as default value for clear checking
        help="Path to the pysandboxes configuration file."
    )
    parser.add_argument(
        "--os-sandbox",
        dest="os_sandbox",
        type=str,
        default="subprocess",  # Use None as default value for clear checking
        help="Choice the os-sandbox provider."
    )
    parser.add_argument(
        "--learn",
        dest="learn",
        type=str,
        default=None,  # Use None as default value for clear checking
        help="The learning path."
    )
    args = parser.parse_args()
    kwargs = {}
    if args.learn:
        kwargs = {"learn": args.learn}
    logger.info(f"Start mcp_server with {args}")
    return run_mcp_server(
        args.os_sandbox,
        args.transport,
        args.config_path,
        **kwargs
    )


# Run the mcp over stdio
if __name__ == "__main__":  # FIXME: resoudre le __main__
    sys.exit(main())
