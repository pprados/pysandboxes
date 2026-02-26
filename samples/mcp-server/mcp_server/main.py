import logging
import sys

from .run_calc import run_mcp_server

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


def main() -> int:
    transport = "stdio"
    if len(sys.argv) > 1:
        transport = sys.argv[1]
    logger.info(f"Start mcp_server with transport={transport}")
    return run_mcp_server(transport)


# Run the mcp over stdio
if __name__ == "__main__":  # FIXME: resoudre le __main__
    sys.exit(main())
