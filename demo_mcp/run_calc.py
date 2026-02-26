import logging
from operator import add, sub, mul, truediv
from typing import Literal

# from mcp.mcp import Server
# from fastmcp import FastMCP, Context
from mcp.server.fastmcp import FastMCP, Context

from pysandboxes import sandbox, sandboxes

logging.root.setLevel(logging.DEBUG)  # FIXME
logging.getLogger("mcp.server.sse").setLevel(logging.WARNING)
logging.getLogger("sse_starlette.sse").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# from mcp.mcp.fastmcp.sse import SseProtocol

mcp = FastMCP("My Calculator Server",
              host="127.0.0.1",
              port=8000,
              log_level=logging.getLevelName(logger.getEffectiveLevel())  # type: ignore[arg-type]
              )


# Define the calculator tool
# @sandbox
@mcp.tool(name="evaluate_expression",
          description="Evaluates a mathematical expression and returns the result")
async def evaluate_expression(expression: str, ctx: Context) -> float:
    return await _evaluate_expression(expression)

@sandbox
async def _evaluate_expression(expression: str) -> float:
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


def run_calc_server(transport:str) -> int:
    try:
        with sandboxes(
            config_path="demo_mcp/.py-sandboxes",
            os_sandbox="None",
            learn=".py-sandboxes",
        ):
            mcp.run(transport=transport)  # type: ignore[arg-type]
        # mcp.run(transport=transport,  # type: ignore[arg-type]
        #         # host="127.0.0.1", port=8000
        #         )
    except KeyboardInterrupt:
        logger.info("Keyboard Interrupt")
        pass
    return 0

async def async_run_server(transport:Literal["stdio", "sse", "streamable-http"]) -> int:
    return run_calc_server(transport)

