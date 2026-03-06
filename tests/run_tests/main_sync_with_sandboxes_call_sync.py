from pysandboxes import sandboxes

from .differents_usages import (
    SIZE_OF_LOOP,
    async_init_sandbox,
    init_log_level,
    logger,
    synchronize_function,
)


def main() -> None:
    init_log_level()
    logger.info("--------- Sync Run with sandboxes call Sync")
    for _ in range(0, SIZE_OF_LOOP):
        logger.info("Use 'with sandboxes'")
        with sandboxes(
            init_fn=async_init_sandbox,
            graceful_shutdown=True,
        ):
            synchronize_function()


if __name__ == "__main__":
    main()
