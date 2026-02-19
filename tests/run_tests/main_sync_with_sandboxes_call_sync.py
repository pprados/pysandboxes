from pysandboxes import sandboxes

from .differents_usages import *


def main():
    init_log_level()
    logger.info("--------- Sync Run with sandboxes call Sync")
    for i in range(0, SIZE_OF_LOOP):
        logger.info("Use 'with sandboxes'")
        with sandboxes(
            init_fn=async_init_sandbox,
            graceful_shutdown=True,
        ):
            synchronize_function()


if __name__ == "__main__":
    main()
