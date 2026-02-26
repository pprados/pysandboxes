import logging
import sys

from .run_calc import run_calc_server

logger = logging.getLogger(__name__)

level = logging.DEBUG
format = "%(levelname)-5s [%(process)d] %(name)s: %(message)s"
logging.getLogger("Pysandboxes").setLevel(level)
logging.getLogger("pysandboxes").setLevel(level)
logging.getLogger("pysandboxes.remote.firejail_daemon").setLevel(level)

logging.basicConfig(
    level=level,
    format=format,
)

# Run the mcp over stdio
if __name__ == "__main__":
    transport = "stdio"
    if len(sys.argv) > 1:
        transport = sys.argv[1]
    errlevel = run_calc_server(transport)
    sys.exit(errlevel)
