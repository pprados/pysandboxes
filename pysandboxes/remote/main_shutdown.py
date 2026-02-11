import logging

from pysandboxes.learning import is_learning_mode, generate_config_from_learning

logger = logging.getLogger(__name__)


async def shutdown():
    if is_learning_mode():
        generate_config_from_learning()
