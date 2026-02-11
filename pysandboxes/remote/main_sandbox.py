#!/usr/bin/env python3
import argparse
import asyncio
import importlib
import logging
import os
import pickle
import sys
import threading
from pathlib import Path
from typing import Optional

from .python_in_sb import python_in_sb
from .subprocess_daemon import DaemonParameters
from .tools import set_pdeathsig
from ..private_loop import set_sandbox_loop
from ..tools import SyncOrAsyncFunc, set_is_in_sandbox

logger = logging.getLogger("pysandboxes.remote.main_sandbox")


# %%

def main() -> int:
    threading.main_thread().name = "DaemonMainThread"
    logging.basicConfig(stream=sys.stderr, level=logging.ERROR)

    parser = argparse.ArgumentParser(
        description="Start a Python-sandbox daemon inside os-sandbox."
    )

    parser.add_argument("--_python-sb",
                        action='store_true',
                        default=False,
                        help="_internal parameter")

    parser.add_argument("--_named-pipe",
                        help="_internal parameter")

    # Parse the arguments provided by the user
    sandboxes_parsed, sandboxes_args = parser.parse_known_args()

    # -------------
    # Read all configuration from named-pipe until EOF
    assert sandboxes_parsed._named_pipe, "Set parameter --_named-pipe <path>"
    pickle_data = Path(sandboxes_parsed._named_pipe).read_bytes()
    process_config: DaemonParameters = pickle.loads(pickle_data)
    if not process_config:
        raise RuntimeError("Impossible to read the config body from stdin")

    # Adjuste the root log level and format
    root_logger = logging.getLogger()
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

    from pysandboxes.main_logger import pysandboxes_logger
    if use_py_sandbox:
        # Activate python sandbox
        from pysandboxes.py_sandbox import activate_sandboxes
        activate_sandboxes(
            all_rules,
            dict(os.environ)
        )

    # Call init function
    # Note: the init_function is called AFTER the activation of the python sandbox
    init_fn: Optional[SyncOrAsyncFunc] = None
    if process_config.init_fn:
        module_name, function_name = str(process_config.init_fn).split(':', 1)
        set_is_in_sandbox(True)
        module = importlib.import_module(module_name)
        set_is_in_sandbox(False)  # Learn the import during the import
        init_fn = getattr(module, function_name)

    # Use python-sb command?
    if sandboxes_parsed._python_sb:
        return python_in_sb(
            all_rules,
            sandboxes_args)

    # Else, start the daemon
    if use_py_sandbox:
        pysandboxes_logger.info(
            f"Start a py-sandbox encapsulated in an os-sandox of type {os_sandbox!r}")
    else:
        pysandboxes_logger.info(
            f"Start ONLY an os-sandox of type {os_sandbox!r}")

    from .local_task_daemon import LocalTaskDaemon
    task_daemon = LocalTaskDaemon(process_config.token)

    async def _run():
        try:
            from tblib import pickling_support

            pickling_support.install()

            set_sandbox_loop(asyncio.get_running_loop())
            await task_daemon.start(
                all_rules=all_rules,
                log_level=process_config.log_level,
                init_fn=init_fn,
            )
            await task_daemon.join()
            return 0
        finally:
            await task_daemon.shutdown()

    asyncio.run(_run())


if __name__ == "__main__":
    # Kill this process when the parent is killed
    set_pdeathsig()
    rc = 0
    try:
        rc = main()
    except SystemExit as e:
        rc = int(e.code)
    except KeyboardInterrupt:
        rc = 0
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        rc = 1
    except Exception as e:
        logger.error(f"Exception: {e}", exc_info=True)
        rc = 1
    os._exit(rc)
