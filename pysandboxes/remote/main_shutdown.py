import logging

from pysandboxes.learning import is_learning_mode, generate_config_from_learning

logger = logging.getLogger(__name__)


def shutdown():
    logger.info("Shutting down... the daemon")
    if is_learning_mode():
        generate_config_from_learning()
