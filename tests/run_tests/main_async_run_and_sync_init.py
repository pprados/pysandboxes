
import pysandboxes
from .differents_usages import *

def main():
    init_log_level()
    for i in range(0, 1):
        logger.info("Use 'pysandboxes.run()' and a synchronize 'init_fn'")
        pysandboxes.run(
            asynchronize_function(),
            init_fn = sync_init_sandbox
        )

if __name__ == "__main__":
    main()