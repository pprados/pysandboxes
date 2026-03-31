#!/usr/bin/env python3
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Main sandbox process entry point for PySandboxes remote execution.

This module serves as the main entry point for sandbox processes that run in
isolated environments (subprocess, firejail, etc.). It handles configuration
loading, sandbox initialization, and server startup for remote code execution.

The main process:
1. Loads configuration from named pipes
2. Activates Python-level sandboxing if enabled
3. Starts the SSE server daemon for remote communication
4. Handles graceful shutdown and error handling
"""

import argparse
import asyncio
import importlib
import logging
import os
import pickle
import sys
from logging import StreamHandler
from pathlib import Path

from pysandboxes.config import RELEASE
from pysandboxes.guard_socket import set_pin_dns
from pysandboxes.learning import (
    generate_config_from_learning,
    set_learning_mode,
    set_learning_path,
)
from pysandboxes.main_logger import config_log
from pysandboxes.os_sandbox import providers_factory
from pysandboxes.remote.sse_server_daemon import SSEServerDaemon

from ..tools import SyncOrAsyncFunc, set_is_in_sandbox
from .python_in_sb import python_in_sb
from .sse_client_subprocess_daemon import DaemonParameters
from .tools import set_pdeathsig

logger = logging.getLogger("pysandboxes.remote.main_sandbox")


def _debug_log() -> None:
    logging.basicConfig(
        force=True,
        level=logging.DEBUG,
        format="- %(levelname)s - %(message)s",
    )
    sandbox_level = logging.DEBUG
    uvicorn_log_level = logging.WARNING
    config_log(sandbox_level)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(uvicorn_log_level)
    logging.getLogger("uvicorn.error").setLevel(uvicorn_log_level)
    logging.getLogger("aiohttp_sse_client.client").setLevel(uvicorn_log_level)
    logging.getLogger("Pysandboxes").setLevel(logging.INFO)
    logging.getLogger("pysandboxes").setLevel(sandbox_level)
    logging.getLogger("pysandboxes.guard_import").setLevel(logging.INFO)
    logging.getLogger("pysandboxes.remote.firejail_daemon").setLevel(sandbox_level)
    logger.debug(
        "*** Start main_sandbox\n"
        + " ".join((repr(c) if " " in c else c for c in sys.argv))
    )


# %%


async def run_server(process_config: DaemonParameters) -> int:
    """Run the sandbox server with the provided configuration.

    Args:
        process_config: Configuration parameters for the daemon process.

    Returns:
        Exit code (0 for success).
    """
    from pysandboxes.main_logger import pysandboxes_logger

    # Call init function
    # Note: the init_function is called AFTER the activation of the python sandbox
    init_fn: SyncOrAsyncFunc | None = None
    if process_config.init_fn:
        module_name, function_name = str(process_config.init_fn).split(":", 1)
        set_is_in_sandbox(True)
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            pysandboxes_logger.error(
                "Impossible to import the module %s", repr(module_name)
            )
            sys.exit(-1)
        set_is_in_sandbox(False)  # Learn the import during the import
        assert hasattr(module, function_name)
        init_fn = getattr(module, function_name)

    # Else, _start the daemon
    all_rules = process_config.all_rules
    os_sandbox = all_rules.os_sandbox
    assert os_sandbox in ("subprocess", "firejail", "unshare")
    if all_rules.use_py_sandbox:
        pysandboxes_logger.info(
            f"Start a py-sandbox encapsulated in an os-sandox of type {os_sandbox!r}"
        )
    else:
        pysandboxes_logger.info(f"Start ONLY an os-sandox of type {os_sandbox!r}")

    from pysandboxes.os_sandbox import _set_current_daemon

    server_daemon: SSEServerDaemon = providers_factory["_sse_server"](
        process_config.token,
        port=process_config.port,
    )
    assert isinstance(server_daemon, SSEServerDaemon)
    _set_current_daemon(server_daemon)
    await server_daemon._start(
        process_config.all_rules,
        envs=os.environ,
        log_level=process_config.log_level,
        init_fn=init_fn,
    )
    set_learning_mode(all_rules.learn)
    logger.debug("join server_daemon...")
    await server_daemon.join()
    return 0


def main() -> int:
    """Main entry point for the sandbox process.

    Parses command line arguments, loads configuration from named pipe,
    sets up logging, and starts either the server or python-sb mode.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    logging.getLogger().addHandler(StreamHandler(None))  # Set default handler to stderr
    if not RELEASE:
        _debug_log()

    parser = argparse.ArgumentParser(
        description="Start a Python-sandbox daemon inside os-sandbox."
    )

    parser.add_argument(
        "--_python-sb", action="store_true", default=False, help="_internal parameter"
    )

    parser.add_argument("--_named-pipe", help="_internal parameter")

    # Parse the arguments provided by the user
    sandboxes_parsed, sandboxes_args = parser.parse_known_args()

    # -------------
    # Read all configuration from named-pipe until EOF
    assert sandboxes_parsed._named_pipe, "Set parameter --_named-pipe <path>"
    pickle_data = Path(sandboxes_parsed._named_pipe).read_bytes()
    process_config: DaemonParameters = pickle.loads(pickle_data)
    if not process_config:
        raise RuntimeError("Impossible to read the config body from stdin")

    # Add ident inside the sandbox
    log_format = " " + process_config.log_format
    # Adjuste the root log level and format
    config_log(process_config.log_level, log_format, process_config.use_rich_handler)
    logger.debug("config body and token successfully read from named pipe")

    all_rules = process_config.all_rules

    # Initialize learn
    set_learning_path(all_rules.learning_path)
    set_pin_dns(all_rules.pin_dns)

    # In this case, use the standard loop in place of the private sandbox loop

    if all_rules.use_py_sandbox:
        # Activate python sandbox
        from pysandboxes.py_sandbox import activate_sandboxes

        activate_sandboxes(all_rules, os.environ)

    # Use python-sb command?
    if sandboxes_parsed._python_sb:
        set_learning_mode(all_rules.learn)
        return python_in_sb(all_rules, sandboxes_args)

    # Else _start the server
    return asyncio.run(run_server(process_config))


if __name__ == "__main__":
    # Kill this process when the parent is killed
    set_pdeathsig()
    rc = 0
    try:
        rc = main()
    except SystemExit as e:
        if e.code is not None:
            rc = int(e.code)
        else:
            rc = 0
    except KeyboardInterrupt:
        logger.debug("Except KeyboardInterrupt")
        generate_config_from_learning()
        rc = 0
    except RuntimeError as e:
        logger.exception(f"Unknown exception: {e}")
        print(str(e), file=sys.stderr)
        rc = 1
    except Exception as e:
        logger.exception(f"Unknown exception: {e}")
        rc = 1
    logger.debug("main_sandbox exit with errorlevel=%s", rc)
    os._exit(rc)
