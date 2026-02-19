import pysandboxes

from .differents_usages import *


def main():
    init_log_level()
    logger.info("--------- Async Run and Async Init")
    for i in range(0, SIZE_OF_LOOP):
        logger.info("Use 'pysandboxes.run()' and a asynchronize 'init_fn'")
        pysandboxes.run(asynchronize_function(), init_fn=async_init_sandbox)


if __name__ == "__main__":
    main()
