from .differents_usages import *


def main():
    init_log_level()
    for i in range(0, 1):
        logger.info("Use 'with sandboxes'")
        with sandboxes(
                init_fn=async_init_sandbox,
                graceful_shutdown=True,
        ):
            synchronize_function()


if __name__ == "__main__":
    main()
