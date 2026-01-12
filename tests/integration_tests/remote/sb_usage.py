import logging

from pysandboxes import sandbox

logger = logging.getLogger(__name__)

@sandbox
def run_in_sandbox():
    logger.warning("Run 'run_in_sandbox()' in sandbox")
    return 42

