#!/usr/bin/env python3
import argparse
import asyncio
import importlib
import logging
import os
import sys
import threading
from typing import Optional

from tblib import pickling_support

from .subprocess_daemon import SubProcessParameters
from .tools import configure_logging_level, \
    set_pdeathsig, from_b85
from ..learning import is_learning_mode, generate_config_from_learning
from ..private_loop import set_sandbox_loop
from ..tools import SyncOrAsyncFunc

logger = logging.getLogger(__name__)

pickling_support.install()

# %%

async def main() -> int:
    threading.main_thread().name="DaemonMainThread"
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)

    parser = argparse.ArgumentParser(
        description="Start a Python-sandbox daemon inside os-sandbox."
    )

    # Add the verbose argument.
    # action='count' is key here: it counts how many times the argument is present.
    parser.add_argument(
        '-v', '--verbose',
        action='count',
        default=0,  # Default value if no -v is provided
        help='Increase output verbosity. '
             'Use '
             '-v for WARNING, '
             '-vv for INFO, '
             '-vvv for DEBUG, '
             '-vvvv for all messages.'
    )

    # Parse the arguments provided by the user
    args = parser.parse_args()

    log_level = configure_logging_level(args.verbose)
    logging.getLogger().setLevel(log_level)

    # -------------
    # Read all configuration from stdin until EOF
    process_config: Optional[SubProcessParameters] = None
    for line in sys.stdin:
        process_config = from_b85(line.strip())
        break
    if not process_config:
        raise RuntimeError("Impossible to read the config body from stdin")

    # Adjuste the root log level and format
    root_logger=logging.getLogger()
    root_logger.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(process_config.log_format))
    root_logger.addHandler(handler)
    root_logger.setLevel(process_config.log_level)
    logger.debug("config body and token successfully read from stdin")


    all_rules = process_config.all_rules
    os_sandbox = all_rules.os_sandbox
    use_py_sandbox = all_rules.use_py_sandbox

    # In this case, use the standard loop in place of the private sandbox loop
    set_sandbox_loop(asyncio.get_running_loop())

    from pysandboxes.main_logger import pysandboxes_logger
    if use_py_sandbox:
        # Activate python sandbox
        from pysandboxes.py_sandbox import activate_sandboxes
        activate_sandboxes(
            all_rules,
            dict(os.environ)
        )

        pysandboxes_logger.info(
            f"Start a py-sandbox encapsulated in an os-sandox of type {os_sandbox!r}")
    else:
        pysandboxes_logger.info(
            f"Start ONLY an os-sandox of type {os_sandbox!r}")

    # Call init function
    # Note: the init_function is called AFTER the activation of the python sandbox
    init_fn: Optional[SyncOrAsyncFunc] = None
    if process_config.init_fn:
        module_name, function_name = str(process_config.init_fn).split(':', 1)
        module = importlib.import_module(module_name)
        init_fn = getattr(module, function_name)

    # Start the daemon
    from .local_task_daemon import LocalTaskDaemon
    task_daemon = LocalTaskDaemon(process_config.token)
    try:
        await task_daemon.start(
            all_rules=all_rules,
            log_level=log_level,
            envs=None,
            init_fn=init_fn,
        )
        await task_daemon.join()
        return 0
    finally:
        await task_daemon.shutdown()


def shutdown():
    logger.info("Shutting down... the daemon")
    if is_learning_mode():
        generate_config_from_learning()

if __name__ == "__main__":
    # Kill this process when the parent is killed
    set_pdeathsig()
    rc = 0
    try:
        rc = asyncio.run(main())
    except SystemExit as e:
        rc = int(e.code)
    except KeyboardInterrupt:
        rc = 0
    except Exception as e:
        logger.error(f"Exception: {e}", exc_info=True)
        rc = -1
    sys.exit(rc)
