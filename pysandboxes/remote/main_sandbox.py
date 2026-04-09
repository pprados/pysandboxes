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
import subprocess
import sys
from logging import StreamHandler
from pathlib import Path

from .._os_sandbox import providers_factory
from ..config import DEBUG
from ..guard_socket import set_pin_dns
from ..learning import (
    generate_config_from_learning,
    set_learning_mode,
    set_learning_path,
)
from ..main_logger import config_log
from ..remote.sse_server_daemon import SSEServerDaemon
from ..tools import SyncOrAsyncFunc, set_is_in_sandbox
from .client_subprocess_sse_daemon import DaemonParameters
from .python_in_sb import python_in_sb
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
        "*** Start main_sandbox ***\n"
        + " ".join((repr(c) if " " in c else c for c in sys.argv))
    )


# %%


def run_guest(process_config: DaemonParameters) -> int:
    """Run inside VM guest: same init as main_sandbox then python_in_sb or run_server.

    Used by QEMU guest bootstrap when config is already loaded from the pipe.
    """
    log_format = " " + process_config.log_format
    config_log(process_config.log_level, log_format, process_config.use_rich_handler)
    all_rules = process_config.all_rules
    set_learning_path(all_rules.learning_path)
    # set_pin_dns already called in main() before run_guest(); do not call again (assert in guard_socket)
    # Restrict process env to only profile-allowed vars (VM may have USER, HOME, etc.)
    allowed_env_keys = set(all_rules.envs.keys())
    for key in list(os.environ.keys()):
        if key not in allowed_env_keys:
            del os.environ[key]
    for k, v in dict(all_rules.envs).items():
        os.environ[k] = str(v) if v is not None else ""
    # In QEMU guest, root_path from host is wrong; use cwd so bind=./tmp works
    all_rules = all_rules._replace(root_path=Path.cwd())
    import pysandboxes
    from pysandboxes.py_sandbox import activate_sandboxes

    pysandboxes.os_sandbox = all_rules.os_sandbox
    activate_sandboxes(all_rules, os.environ)
    guest_run_dir = getattr(process_config, "guest_run_dir", None)

    def _write_exitcode(code: int) -> None:
        if guest_run_dir:
            try:
                Path(guest_run_dir).joinpath("exitcode").write_text(str(code))
            except OSError:
                pass

    try:
        python_main_args = getattr(process_config, "python_main_args", ()) or ()
        if python_main_args:
            set_learning_mode(all_rules.learn)
            # In guest VM, use subprocess so start_daemon() launches a local Python server
            # instead of trying to start another QEMU.
            os.environ["OS_SANDBOX"] = "subprocess"
            from pysandboxes.python_sb import (
                PYTHON_OUTPUT_END,
                PYTHON_OUTPUT_START,
            )

            print(PYTHON_OUTPUT_START, flush=True, file=sys.stderr)
            try:
                rc = python_in_sb(all_rules, list(python_main_args))
            finally:
                print(PYTHON_OUTPUT_END, flush=True, file=sys.stderr)
        else:
            rc = asyncio.run(run_server(process_config))
        _write_exitcode(rc)
        return rc
    except SystemExit as e:
        rc = int(e.code) if e.code is not None else 0
        _write_exitcode(rc)
        raise
    except Exception:
        _write_exitcode(1)
        raise


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
    assert os_sandbox in (
        "subprocess",
        "firejail",
        "unshare",
        "landlock",
        "bwrap",
        "qemu",
    )
    if all_rules.use_py_sandbox:
        pysandboxes_logger.info(
            f"Start a py-sandbox encapsulated in an os-sandox of type {os_sandbox!r}"
        )
    else:
        pysandboxes_logger.info(f"Start ONLY an os-sandox of type {os_sandbox!r}")

    from pysandboxes._os_sandbox import _set_current_daemon

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
    logger.info(
        "SSE server listening on 0.0.0.0:%s; joining server_daemon (blocking until shutdown)",
        process_config.port,
    )
    await server_daemon.join()
    return 0


def main() -> int:
    """Main entry point for the sandbox process.

    Parses command line arguments, loads configuration from named pipe,
    sets up logging, and starts either the server or python-sb mode.

    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    print("[pysandbox] TRACE: main_sandbox main() started", flush=True)
    logging.getLogger().addHandler(StreamHandler(None))  # Set default handler to stderr
    if DEBUG:
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
    # Read all configuration from named-pipe (or config file for QEMU) until EOF
    assert sandboxes_parsed._named_pipe, "Set parameter --_named-pipe <path>"
    config_path = Path(sandboxes_parsed._named_pipe.strip())
    print(
        f"[pysandbox] TRACE: main_sandbox opening pipe for read: {config_path!s}",
        flush=True,
    )
    pickle_data: bytes = config_path.read_bytes()
    print("[pysandbox] TRACE: main_sandbox pipe read done, got config", flush=True)
    # Only the parent process feeds the named_pipe; no risk of malicious pickle
    # injection.
    process_config: DaemonParameters = pickle.loads(memoryview(pickle_data))
    if not process_config:
        raise RuntimeError("Impossible to read the config body from stdin")

    # Apply iptables rules in VM guest (QEMU) when provided
    netfilter_rules = getattr(process_config, "netfilter_rules", ()) or ()
    if netfilter_rules:
        # Use absolute path to avoid PATH symlink issues in guest (e.g. 9p mounts)
        for candidate in ("/usr/sbin/iptables-restore", "/sbin/iptables-restore"):
            if Path(candidate).is_file():
                subprocess.run(
                    [candidate, "--noflush"],
                    input="\n".join(netfilter_rules).encode(),
                    check=False,
                )
                break
        else:
            logger.warning(
                "iptables-restore not found at /usr/sbin or /sbin; skipping netfilter rules"
            )

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

    # Activate python sandbox
    import pysandboxes
    from pysandboxes.py_sandbox import activate_sandboxes

    pysandboxes.os_sandbox = all_rules.os_sandbox
    activate_sandboxes(all_rules, os.environ)

    # QEMU/python_sb: config was written by host with python_main_args → run user module in guest
    python_main_args = getattr(process_config, "python_main_args", ()) or ()
    if python_main_args:
        return run_guest(process_config)

    # Use python-sb command? (subprocess/firejail path: args from CLI)
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
