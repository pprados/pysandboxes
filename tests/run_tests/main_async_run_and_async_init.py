import pysandboxes

from .differents_usages import (
    SIZE_OF_LOOP,
    async_init_sandbox,
    asynchronize_function,
    init_log_level,
    logger,
)


def main() -> None:
    init_log_level()
    logger.info("--------- Async Run and Async Init")
    for _ in range(0, SIZE_OF_LOOP):
        logger.info("Use 'pysandboxes.run()' and a asynchronize 'init_fn'")
        pysandboxes.run(asynchronize_function(), init_fn=async_init_sandbox)


if __name__ == "__main__":
    main()
