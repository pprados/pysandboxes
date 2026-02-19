import pysandboxes

from .differents_usages import *


def main() -> None:
    init_log_level()
    logger.info("--------- Async Run and Sync Init")
    for i in range(0, SIZE_OF_LOOP):
        logger.info("Use 'pysandboxes.run()' and a synchronize 'init_fn'")
        pysandboxes.run(asynchronize_function(), init_fn=sync_init_sandbox)


if __name__ == "__main__":
    main()
