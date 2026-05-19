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
import logging
import os
import pickle
import socket as _socket_mod
import subprocess
import sys
import time
from logging import StreamHandler
from pathlib import Path
from typing import Any, cast

from ..config import DEBUG
from .daemon_parameters import DaemonParameters

# Intentionally minimal module-level imports: the QEMU guest runs ``python -m
# ...main_sandbox`` with a long PYTHONPATH; pulling learning/guards/remote.tools
# (ctypes) at import time has caused SIGSEGV before ``main()`` runs.

logger = logging.getLogger("pysandboxes.remote.main_sandbox")


def _qemu_show_boot_console_truthy_from_rules(all_rules: Any) -> bool:
    """Same truthy rule as ``qemu_setup._qemu_show_boot_console_truthy`` (avoid importing that module)."""
    if all_rules is None:
        return False
    params = getattr(all_rules, "os_sandbox_params", None)
    if not params:
        return False
    raw = str(params.get("show_boot_console", "false")).strip().lower()
    return raw in ("true", "1", "yes")


def _qemu_show_boot_console_guest_trace_enabled(
    process_config: DaemonParameters,
) -> bool:
    """QEMU guest diagnostics: same profile knob as host VM serial / verbose bootstrap."""
    return bool(
        getattr(process_config, "guest_run_dir", None)
        and _qemu_show_boot_console_truthy_from_rules(process_config.all_rules)
    )


def _qemu_show_boot_console_guest_trace(
    process_config: DaemonParameters, msg: str
) -> None:
    """Stderr breadcrumbs in QEMU guest when ``qemu.show_boot_console`` is truthy."""
    if not _qemu_show_boot_console_guest_trace_enabled(process_config):
        return
    print(f"[PYSANDBOX_DIAG] {msg}", file=sys.stderr, flush=True)


def _debug_log() -> None:
    from ..main_logger import config_log

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


# Slirp gateway; match bwrap_sse_daemon / unshare
_SLIRP_GW = "10.0.2.2"
_NETWORK_READY_TIMEOUT = 15.0
_NETWORK_READY_INTERVAL = 0.5


def _wait_network_ready() -> None:
    """Block until the slirp network is reachable (bwrap/unshare namespace).

    Retries connecting to the slirp gateway for up to _NETWORK_READY_TIMEOUT
    seconds so the child does not start before the namespace is routable.
    Only a successful connect counts; connection refused or other errors are retried.
    """
    deadline = time.monotonic() + _NETWORK_READY_TIMEOUT
    while time.monotonic() < deadline:
        try:
            s = _socket_mod.socket(_socket_mod.AF_INET, _socket_mod.SOCK_STREAM)
            s.settimeout(2.0)
            s.connect((_SLIRP_GW, 80))
            s.close()
            return
        except OSError:
            time.sleep(_NETWORK_READY_INTERVAL)
            continue
        except Exception:
            time.sleep(_NETWORK_READY_INTERVAL)
            continue
    logger.warning(
        "Network not reachable after %.0fs; continuing anyway. "
        "If using bwrap --unshare-net, ensure slirp4netns runs and iptables has "
        "cap_net_admin (or use bwrap.share-net=yes).",
        _NETWORK_READY_TIMEOUT,
    )


def run_guest(process_config: DaemonParameters) -> int:
    """Run inside VM guest: same init as main_sandbox then python_in_sb or run_server.

    Used by QEMU guest bootstrap when config is already loaded from the pipe.
    """
    from ..learning import set_learning_mode, set_learning_path
    from ..main_logger import config_log

    _qemu_show_boot_console_guest_trace(process_config, "run_guest: start")
    log_format = " " + process_config.log_format
    config_log(process_config.log_level, log_format, process_config.use_rich_handler)
    all_rules = process_config.all_rules
    set_learning_path(all_rules.learning_path)
    # set_pin_dns already called in main() before run_guest(); do not call again (assert in guard_socket)
    # Env + root_path for QEMU guest were applied in main() before activate_sandboxes.
    guest_run_dir = getattr(process_config, "guest_run_dir", None)

    def _write_exitcode(code: int) -> None:
        if not guest_run_dir:
            logger.warning(
                "QEMU guest: guest_run_dir missing; cannot write exitcode %s", code
            )
            return
        try:
            path = Path(guest_run_dir).joinpath("exitcode")
            with path.open("w", encoding="utf-8") as f:
                f.write(str(code))
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
        except OSError as e:
            logger.warning("QEMU guest: failed to write exitcode: %s", e)

    try:
        python_main_args = getattr(process_config, "python_main_args", ()) or ()
        if python_main_args:
            set_learning_mode(all_rules.learn)
            # In guest VM, use subprocess so start_daemon() launches a local Python server
            # instead of trying to start another QEMU.
            os.environ["OS_SANDBOX"] = "subprocess"
            _qemu_show_boot_console_guest_trace(
                process_config, "run_guest: before python_in_sb"
            )
            from .python_in_sb import python_in_sb
            from .vm_sse_daemon import (
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
    import importlib

    from ..learning import set_learning_mode
    from ..tools import set_is_in_sandbox

    _qemu_show_boot_console_guest_trace(process_config, "run_server: start")
    from pysandboxes.main_logger import pysandboxes_logger

    # Call init function
    # Note: the init_function is called AFTER the activation of the python sandbox
    init_fn: Any = None
    if process_config.init_fn:
        module_name, function_name = str(process_config.init_fn).split(":", 1)
        set_is_in_sandbox(True)
        try:
            # reason: init_fn declared by the trusted parent
            # nosemgrep: python.lang.security.audit.non-literal-import.non-literal-import
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

    from pysandboxes._os_sandbox import _set_current_daemon, providers_factory

    from ..remote.sse_server_daemon import SSEServerDaemon

    server_daemon = cast(
        SSEServerDaemon,
        providers_factory["_sse_server"](
            process_config.token,
            port=process_config.port,
        ),
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
    pickle_data: bytes = config_path.read_bytes()
    # Only the parent process feeds the named_pipe; no risk of malicious pickle
    # injection.
    # reason: payload written by the trusted parent
    # nosemgrep: python.lang.security.deserialization.pickle.avoid-pickle
    process_config: DaemonParameters = pickle.loads(memoryview(pickle_data))
    if not process_config:
        raise RuntimeError("Impossible to read the config body from stdin")

    if _qemu_show_boot_console_guest_trace_enabled(process_config):
        import faulthandler

        faulthandler.enable(file=sys.stderr, all_threads=True)
    _qemu_show_boot_console_guest_trace(
        process_config,
        "main: config loaded, python_main_args="
        + repr(getattr(process_config, "python_main_args", ())),
    )

    netfilter_rules = getattr(process_config, "netfilter_rules", ()) or ()
    # Wait for slirp4netns readiness when in isolated network namespace (e.g. bwrap --unshare-net)
    # Fd is passed via config when available (unshare inherits env; bwrap does not pass fds to inner process)
    slirp_ready_fd = getattr(process_config, "slirp_ready_fd", None)
    if slirp_ready_fd is not None:
        try:
            with os.fdopen(slirp_ready_fd, "rb") as f:
                f.read(1)
        except (ValueError, OSError):
            pass

    if netfilter_rules:
        # Bring up loopback when in a new network namespace (required before iptables)
        for ip_cmd in ("/usr/sbin/ip", "/sbin/ip", "ip"):
            try:
                subprocess.run(
                    [ip_cmd, "link", "set", "lo", "up"],
                    check=False,
                    capture_output=True,
                )
                break
            except FileNotFoundError:
                continue
        # Apply iptables rules in guest (QEMU) or in user-land namespace (bwrap --unshare-net)
        for candidate in ("/usr/sbin/iptables-restore", "/sbin/iptables-restore"):
            if Path(candidate).is_file():
                r = subprocess.run(
                    [candidate, "--noflush"],
                    input="\n".join(netfilter_rules).encode(),
                    check=False,
                    capture_output=True,
                )
                if r.returncode != 0 and r.stderr and b"Permission denied" in r.stderr:
                    logger.warning(
                        "iptables-restore failed (permission denied). "
                        "For bwrap --unshare-net you may need root or cap_net_admin; "
                        "or set bwrap.share-net=yes to use host network."
                    )
                break
        else:
            logger.warning(
                "iptables-restore not found at /usr/sbin or /sbin; skipping netfilter rules"
            )

    # After slirp setup: loop until network is reachable (bwrap cannot pass pipe fd to inner process)
    if netfilter_rules or getattr(process_config, "wait_network", False):
        _wait_network_ready()

    _qemu_show_boot_console_guest_trace(
        process_config, "main: after netfilter / wait_network"
    )

    from ..learning import set_learning_path
    from ..main_logger import config_log

    # Add ident inside the sandbox
    log_format = " " + process_config.log_format
    # Adjuste the root log level and format
    config_log(process_config.log_level, log_format, process_config.use_rich_handler)
    logger.debug("config body and token successfully read from named pipe")

    all_rules = process_config.all_rules

    # Initialize learn
    set_learning_path(all_rules.learning_path)
    from ..guard_socket import set_pin_dns

    set_pin_dns(all_rules.pin_dns)
    # When pin_dns is set but use_py_sandbox is False, patch resolution so guest uses pinned IPs
    if all_rules.pin_dns:
        import socket as _socket_mod

        from ..guard_socket import apply_pin_dns_resolution

        apply_pin_dns_resolution(_socket_mod)

    # In this case, use the standard loop in place of the private sandbox loop

    # Activate python sandbox
    _qemu_show_boot_console_guest_trace(
        process_config, "main: before import pysandboxes / activate_sandboxes"
    )
    import pysandboxes
    from pysandboxes.py_sandbox import activate_sandboxes

    pysandboxes.os_sandbox = all_rules.os_sandbox
    python_main_args = getattr(process_config, "python_main_args", ()) or ()
    if python_main_args:
        # QEMU guest: cwd-based root_path for rules; env restricted to profile.
        # Must run before activate_sandboxes once (second activate would call
        # tempfile.mkdtemp() under /tmp while guards are already active → RuleFileNotFoundError).
        allowed_env_keys = set(all_rules.envs.keys())
        for key in list(os.environ.keys()):
            if key not in allowed_env_keys:
                del os.environ[key]
        for k, v in dict(all_rules.envs).items():
            os.environ[k] = str(v) if v is not None else ""
        all_rules = all_rules._replace(root_path=Path.cwd())
        process_config = process_config._replace(all_rules=all_rules)
        # Profile allowlist drops bootstrap exports; Rich still needs FORCE_COLOR on serial.
        if getattr(process_config, "guest_run_dir", None):
            os.environ.setdefault("TERM", "xterm-256color")
            os.environ.setdefault("FORCE_COLOR", "1")
    # Guest runs user code inside the VM: do not load qemu/subprocess daemons here
    # (they pull aiohttp/native stack and can segfault in the minimal guest).
    activate_sandboxes(
        all_rules,
        os.environ,
        rules_provider="none" if python_main_args else None,
    )
    _qemu_show_boot_console_guest_trace(
        process_config, "main: after activate_sandboxes"
    )

    # QEMU/python_sb: config was written by host with python_main_args → run user module in guest
    if python_main_args:
        _qemu_show_boot_console_guest_trace(process_config, "main: entering run_guest")
        return run_guest(process_config)

    # Use python-sb command? (subprocess/firejail path: args from CLI)
    if sandboxes_parsed._python_sb:
        from ..learning import set_learning_mode

        set_learning_mode(all_rules.learn)
        from .python_in_sb import python_in_sb

        return python_in_sb(all_rules, sandboxes_args)

    # Else _start the server
    _qemu_show_boot_console_guest_trace(
        process_config, "main: entering asyncio.run(run_server)"
    )
    return asyncio.run(run_server(process_config))


if __name__ == "__main__":
    # Kill this process when the parent is killed
    from .tools import set_pdeathsig

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
        from ..learning import generate_config_from_learning

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
