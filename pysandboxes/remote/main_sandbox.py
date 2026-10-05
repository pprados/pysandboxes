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
import subprocess
import sys
import traceback
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


def _qemu_show_boot_console_guest_trace(process_config: DaemonParameters, msg: str) -> None:
    """Stderr breadcrumbs in QEMU guest when ``qemu.show_boot_console`` is truthy."""
    if not _qemu_show_boot_console_guest_trace_enabled(process_config):
        return
    print(f"[PYSANDBOX_DIAG] {msg}", file=sys.stderr, flush=True)


def _redirect_guest_stderr(guest_run_dir: str | None) -> int | None:
    """Point the guest's stderr at ``<run dir>/stderr`` and return the saved fd.

    QEMU multiplexes the guest console onto a single host stream, so a program run in
    the VM had its stdout and its stderr merged, where the same program run without a
    VM keeps them apart. The run directory is already shared with the host over 9p --
    it is how ``exitcode`` travels -- which makes it the one channel to the host that
    does not go through the console.

    Returns ``None`` when there is no run dir to write to: the caller then keeps the
    console stderr, which is the merged behaviour this replaces.
    """
    if not guest_run_dir:
        return None
    from .qemu_guest_console_io import GUEST_STDERR_FILE

    try:
        handle = Path(guest_run_dir).joinpath(GUEST_STDERR_FILE).open("w", encoding="utf-8")
    except OSError as e:
        logger.warning("QEMU guest: cannot open the stderr channel: %s", e)
        return None
    sys.stderr.flush()
    saved_fd = os.dup(2)
    # The redirect is on the file descriptor, not on sys.stderr: a child process, or a
    # C extension writing to fd 2 directly, must land in the same place as a print().
    os.dup2(handle.fileno(), 2)
    handle.close()
    return saved_fd


def _restore_guest_stderr(saved_stderr_fd: int | None) -> None:
    """Restore the console stderr, after flushing the run dir file for the host."""
    if saved_stderr_fd is None:
        return
    sys.stderr.flush()
    try:
        os.fsync(2)
    except OSError:
        pass
    os.dup2(saved_stderr_fd, 2)
    os.close(saved_stderr_fd)


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
    logger.debug("*** Start main_sandbox ***\n" + " ".join((repr(c) if " " in c else c for c in sys.argv)))


# %%


def run_guest(process_config: DaemonParameters) -> int:
    """Run inside VM guest: same init as main_sandbox then python_in_sb or run_server.

    Used by QEMU guest bootstrap when config is already loaded from the pipe.
    """
    from ..learning import set_learning_path
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
            logger.warning("QEMU guest: guest_run_dir missing; cannot write exitcode %s", code)
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
            # In guest VM, use subprocess so start_daemon() launches a local Python server
            # instead of trying to start another QEMU.
            os.environ["OS_SANDBOX"] = "subprocess"
            _qemu_show_boot_console_guest_trace(process_config, "run_guest: before python_in_sb")
            from .python_in_sb import python_in_sb

            # The two sentinels, from the module that defines them rather than from
            # vm_sse_daemon, which re-exports them: that one pulls the subprocess daemon
            # in, and the guest must not load a daemon (see the preimport block in
            # main()). Both modules are preimported before arming, so neither import
            # reaches the user's python-import rules.
            from .qemu_guest_console_io import (
                PYTHON_OUTPUT_END,
                PYTHON_OUTPUT_START,
            )

            # Sentinels on stdout, not stderr: the user program's stderr is about to be
            # redirected to the shared run dir, so stderr no longer reaches the console
            # the host filters. Both streams are unbuffered here ("-u" in the bootstrap),
            # so the window still opens before the first print() of the program.
            print(PYTHON_OUTPUT_START, flush=True)
            saved_stderr_fd = _redirect_guest_stderr(guest_run_dir)
            try:
                rc = python_in_sb(all_rules, list(python_main_args))
            except Exception:
                # The host reads the guest's stderr from the shared run dir, and only
                # until the interpreter exits. An exception raised here is printed by
                # the interpreter *after* the finally below restored the real stderr,
                # so it would land on the console instead of the caller's stderr and
                # the run would report `returncode=1, stderr=''` -- a guest failure
                # with no cause attached. Report it while the redirect still holds.
                #
                # traceback is imported at module level on purpose: importing it here
                # would happen after arming, be charged to the user's python-import
                # rules, and a profile that does not name it would raise *that* denial
                # instead of the one being reported -- the reporting path erasing the
                # failure it exists to describe.
                traceback.print_exc(file=sys.stderr)
                raise
            finally:
                _restore_guest_stderr(saved_stderr_fd)
                print(PYTHON_OUTPUT_END, flush=True)
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

    _qemu_show_boot_console_guest_trace(process_config, "run_server: start")
    from pysandboxes.main_logger import pysandboxes_logger

    # Call init function
    # Note: the init_function is called AFTER the activation of the python sandbox
    init_fn: Any = None
    if process_config.init_fn:
        module_name, function_name = str(process_config.init_fn).split(":", 1)
        # No enter()/leave() around this import: run_server() is only reached
        # from main(), which entered the sandbox before activating the guards,
        # so bracketing it here changed nothing.
        try:
            # Init_fn declared by the trusted parent
            module = importlib.import_module(module_name)
        except ImportError:
            pysandboxes_logger.error("Impossible to import the module %s", repr(module_name))
            sys.exit(-1)
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
        pysandboxes_logger.info(f"Start a py-sandbox encapsulated in an os-sandox of type {os_sandbox!r}")
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
    logger.info(
        "SSE server listening on 0.0.0.0:%s; joining server_daemon (blocking until shutdown)",
        process_config.port,
    )
    await server_daemon.join()
    return 0


# The backend binaries first: /usr/sbin/iptables-restore goes through /etc/alternatives, which is the host's once a
# profile exposes /etc over the guest's, and then resolves to nothing.
_IPTABLES_RESTORE_PATHS = (
    "/usr/sbin/iptables-nft-restore",
    "/usr/sbin/iptables-legacy-restore",
    "/usr/sbin/iptables-restore",
    "/sbin/iptables-restore",
)


def _apply_netfilter(netfilter_rules: tuple[str, ...]) -> None:
    """Apply the iptables rules in the QEMU guest, where the child is root.

    Fails closed: the profile's socket rules depend on this filter, so the child stops when it cannot be applied.
    """
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
    restore = next((c for c in _IPTABLES_RESTORE_PATHS if Path(c).is_file()), None)
    if restore is None:
        raise RuntimeError(
            f"iptables-restore not found in {', '.join(_IPTABLES_RESTORE_PATHS)}: cannot apply the network filter. "
            "Install iptables in the guest image."
        )
    r = subprocess.run(
        [restore, "--noflush"],
        input="\n".join(netfilter_rules).encode(),
        check=False,
        capture_output=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"iptables-restore failed ({r.returncode}): {r.stderr.decode(errors='replace').strip()}")


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

    # The user's script and its arguments share this command line: neither -h/--help nor an
    # abbreviation of an internal option may be taken from them.
    parser = argparse.ArgumentParser(
        description="Start a Python-sandbox daemon inside os-sandbox.", add_help=False, allow_abbrev=False
    )

    parser.add_argument("--_python-sb", action="store_true", default=False, help="_internal parameter")

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
    # Payload written by the trusted parent
    process_config: DaemonParameters = pickle.loads(memoryview(pickle_data))
    if not process_config:
        raise RuntimeError("Impossible to read the config body from stdin")

    if _qemu_show_boot_console_guest_trace_enabled(process_config):
        import faulthandler

        faulthandler.enable(file=sys.stderr, all_threads=True)
    _qemu_show_boot_console_guest_trace(
        process_config,
        "main: config loaded, python_main_args=" + repr(getattr(process_config, "python_main_args", ())),
    )

    netfilter_rules = getattr(process_config, "netfilter_rules", ()) or ()
    # Only the QEMU guest applies its own filter. bwrap gets no rule: the host loads its filter and waits for
    # slirp4netns before handing the child its config.
    if netfilter_rules:
        _apply_netfilter(netfilter_rules)

    _qemu_show_boot_console_guest_trace(process_config, "main: after netfilter / wait_network")

    from ..learning import set_learning_mode, set_learning_path
    from ..main_logger import config_log
    from ..tools import set_is_in_sandbox

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
    _qemu_show_boot_console_guest_trace(process_config, "main: before import pysandboxes / activate_sandboxes")
    import pysandboxes
    from pysandboxes.py_sandbox import activate_sandboxes

    pysandboxes.os_sandbox = all_rules.os_sandbox
    python_main_args = getattr(process_config, "python_main_args", ()) or ()
    in_guest = bool(getattr(process_config, "guest_run_dir", None))
    if python_main_args or in_guest:
        # The guest's environment is the VM's, not the caller's: the other backends narrow
        # it host-side by choosing the child's env, which a boot cannot do. Both guest paths
        # need this, the daemon one included -- without it partial mode kept the VM's own
        # USER and never saw the variables the profile whitelists.
        # Must run before activate_sandboxes once (second activate would call
        # tempfile.mkdtemp() under /tmp while guards are already active → RuleFileNotFoundError).
        allowed_env_keys = set(all_rules.envs.keys())
        for key in list(os.environ.keys()):
            if key not in allowed_env_keys:
                del os.environ[key]
        for k, v in dict(all_rules.envs).items():
            os.environ[k] = str(v) if v is not None else ""
    if python_main_args:
        # QEMU guest running the program itself: rules are rooted on the cwd.
        all_rules = all_rules._replace(root_path=Path.cwd())
        process_config = process_config._replace(all_rules=all_rules)
        # Profile allowlist drops bootstrap exports; Rich still needs FORCE_COLOR on serial.
        if getattr(process_config, "guest_run_dir", None):
            os.environ.setdefault("TERM", "xterm-256color")
            os.environ.setdefault("FORCE_COLOR", "1")
    if sandboxes_parsed._python_sb or python_main_args:
        # python-sb runs the user program in this process. Load its entry point
        # before arming: once the guards are active, the stdlib imports of
        # python_in_sb (os, logging, pathlib, ...) would be charged to the
        # user's python-import rules and denied.
        #
        # The guest reaches python_in_sb through run_guest() instead of the CLI
        # flag -- it is started as `main_sandbox --_named-pipe ...`, so
        # `_python_sb` is False there and only `python_main_args` marks the path.
        # Importing it after arming captures the *patched* builtins into
        # python_in_sb._RAW_COMPILE, and every script run in the VM then dies on
        # `builtins.compile() is denied by the API guard`.
        #
        # qemu_guest_console_io goes with it: run_guest() reads the two console
        # sentinels from it, and its own stdlib imports (abc, re, time, ...) would be
        # charged to the user's rules just the same -- a profile naming its modules one
        # by one, as a learned one does, then dies on the harness's imports.
        import pysandboxes.remote.python_in_sb  # noqa: F401
        import pysandboxes.remote.qemu_guest_console_io  # noqa: F401
    # The transport pickles an exception together with its tblib traceback, and
    # catch_stdio imports tblib from inside its own except handler. That import
    # belongs to the framework, not to the user: a learned profile can never
    # carry it, since learning only records what a run imported and a run that
    # raised nothing never reached that handler. Denied there, the sandbox fails
    # while reporting a failure and the caller waits out the RPC timeout instead
    # of seeing the exception.
    from ..guard_import import preimport_framework_module

    preimport_framework_module("tblib")

    # Guest runs user code inside the VM: do not load qemu/subprocess daemons here
    # (they pull aiohttp/native stack and can segfault in the minimal guest).
    activate_sandboxes(
        all_rules,
        os.environ,
        rules_provider="none" if python_main_args else None,
    )
    # From here on, this process *is* the sandbox, and the learning mode must be
    # armed at the same moment as the guards. Every deferred import the harness
    # makes after this point -- run_server() starts with `import importlib` --
    # is charged to the user's python-import rules; the import guard only
    # records instead of denying when `is_learning_mode() and is_in_sandbox()`,
    # so both flags have to be raised here. Arming them any later makes learning
    # unable to bootstrap from an absent configuration: the sandbox dies on its
    # own imports before reaching the user's code.
    set_is_in_sandbox(True)
    set_learning_mode(all_rules.learn)
    _qemu_show_boot_console_guest_trace(process_config, "main: after activate_sandboxes")

    # QEMU/python_sb: config was written by host with python_main_args → run user module in guest
    if python_main_args:
        _qemu_show_boot_console_guest_trace(process_config, "main: entering run_guest")
        return run_guest(process_config)

    # Use python-sb command? (subprocess/firejail path: args from CLI)
    if sandboxes_parsed._python_sb:
        from .python_in_sb import python_in_sb

        return python_in_sb(all_rules, sandboxes_args)

    # Else _start the server
    _qemu_show_boot_console_guest_trace(process_config, "main: entering asyncio.run(run_server)")
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
