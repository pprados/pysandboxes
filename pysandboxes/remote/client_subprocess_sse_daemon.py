# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Subprocess-based daemon client for PySandboxes remote execution.

This module implements a subprocess-based daemon that spawns isolated Python
processes for sandboxed code execution. It provides process management,
watchdog functionality, and IPC communication via Server-Sent Events (SSE).

Key components:
- BaseSubProcessDaemon: Base class for subprocess-based sandboxes
- SubProcessDaemon: Standard subprocess implementation
- Process lifecycle management with automatic restart on failure
"""

import asyncio
import errno
import fcntl
import gc
import logging
import os
import pickle
import random
import socket
import sys
import tempfile
import time
import uuid
from asyncio import CancelledError, Task
from asyncio.subprocess import Process
from contextlib import closing
from pathlib import Path
from typing import Any, Callable

import aiohttp
from aiohttp import ClientConnectorError, ClientOSError, ClientTimeout, ServerDisconnectedError

from ..all_rules import AllRules
from ..config import DEBUG
from ..e import SandBoxError
from ..guard_socket import SocketRule
from ..main_logger import pysandboxes_logger
from ..private_loop import sandbox_loop
from ..sb_types import Args, ConfigLine, Envs
from ..tools import Environ, SyncOrAsyncFunc, get_callable_info
from . import main_shutdown
from .base_sse_daemon import BaseSSESandbox
from .daemon_parameters import DaemonParameters
from .parameters import (
    INTERVAL_FOR_PING_DAEMON,
    LOOP_FOR_PING,
    MAX_CONNECT_RETRY,
    POLLING_DELAY,
    RETRY_BASE_DELAY,
    RETRY_FACTOR,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_DELAY,
    RETRY_RESET_DELAY,
    TIMEOUT_FOR_PING,
    TIMEOUT_FOR_START_DAEMON,
    TIMEOUT_FOR_STOP_DAEMON,
)
from .tools import is_transient_connection_error

logger = logging.getLogger(__name__)

DEBUG_LAUNCH = DEBUG or False


def get_log_formatter() -> str:
    """Get the current log formatter pattern.

    Returns:
        Format string for log messages.
    """
    root_logger = logging.getLogger()
    fmt = None
    for h in root_logger.handlers:
        fmt = h.formatter
        break
    if fmt is None:
        # Default formatter if none set explicitly
        fmt = logging.Formatter()
    return fmt._fmt if fmt._fmt else "%(message)s"


def use_rich_handler() -> bool:
    root_handlers = logging.getLogger().handlers
    return any(h.__class__.__name__ == "RichHandler" for h in root_handlers)


async def _write_stream(child_stdin_writer: asyncio.StreamWriter) -> None:
    """Write stdin data to child process.

    Args:
        child_stdin_writer: Stream writer for child process stdin.
    """
    import pty
    import termios
    import tty

    master_fd, slave_fd = pty.openpty()
    old_settings = termios.tcgetattr(sys.stdin.fileno())
    try:
        tty.setraw(sys.stdin.fileno())

        while True:
            try:
                line: str = await asyncio.to_thread(sys.stdin.readline)
                if not line:  # EOF (End Of File)
                    break
                child_stdin_writer.write(line.encode("utf-8"))
                await child_stdin_writer.drain()
            except Exception:
                break
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
        if master_fd:
            os.close(master_fd)


async def _read_stream(stream: asyncio.StreamReader, callback: Callable[[str], None]) -> None:
    """Read data from stream and call callback for each line.

    Args:
        stream: Stream reader to read from.
        callback: Function to call with each line of output.
    """
    while True:
        line: bytes = await stream.readline()
        if line:
            callback(line.decode("utf-8").strip())
        else:
            break


async def _open_fifo_for_write(pipe_path: Path, process: Process) -> int:
    """Open the configuration FIFO for writing without hanging when the sandbox is gone.

    A blocking ``open`` on a FIFO waits for a reader forever, so a sandbox that never
    starts (bwrap refusing an option, a missing binary) would freeze the caller instead
    of reporting the failure. Opening non-blocking turns "no reader yet" into ``ENXIO``,
    which lets us watch the process between attempts; the descriptor is switched back to
    blocking mode so a payload larger than the pipe buffer still writes in one go.
    """
    deadline = time.monotonic() + TIMEOUT_FOR_START_DAEMON
    while True:
        try:
            fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
        except OSError as e:
            if e.errno != errno.ENXIO:
                raise
        else:
            fcntl.fcntl(fd, fcntl.F_SETFL, fcntl.fcntl(fd, fcntl.F_GETFL) & ~os.O_NONBLOCK)
            return fd
        if process.returncode is not None:
            raise SandBoxError(
                f"The sandbox process exited with code {process.returncode} before reading its configuration."
            )
        if time.monotonic() > deadline:
            raise SandBoxError(
                f"The sandbox process did not read its configuration within {TIMEOUT_FOR_START_DAEMON}s."
            )
        await asyncio.sleep(POLLING_DELAY)


@sandbox_loop
async def launch_sandbox(
    cmd: list[str],
    pipe_path: Path,
    envs: Envs,
    process_config: DaemonParameters,
    extra_preexec_fn: Callable[[], None] | None = None,
    pass_fds: tuple[int, ...] = (),
    on_launched: Callable[[int], None] | None = None,
    config_writer: Callable[["DaemonParameters"], None] | None = None,
    stdout: int | None = None,
    stderr: int | None = None,
    stdin: int | None = None,
) -> Process:
    """Launch a sandbox subprocess with the given configuration.

    Args:
        cmd: Command line arguments for the subprocess.
        pipe_path: Path to named pipe for configuration transfer (ignored if config_writer set).
        envs: Environment variables for the subprocess.
        process_config: Configuration parameters to send to subprocess.
        extra_preexec_fn: Optional additional preexec function to run in child.
        pass_fds: File descriptors to keep open in the child process.
        on_launched: Optional callback invoked with the process PID after
            subprocess creation but before writing config to the FIFO.
        config_writer: If set, use instead of FIFO (e.g. HTTP server); called before starting process.
        stdout: Optional file descriptor for child stdout (e.g. to avoid mixing with host console).
        stderr: Optional file descriptor for child stderr.
        stdin: Optional stdin for the child (e.g. ``subprocess.DEVNULL`` so QEMU ``-nographic``
            never blocks reading the parent TTY under ``podman run -it``).

    Returns:
        The launched subprocess.
    """
    use_fifo = config_writer is None
    if use_fifo:
        os.mkfifo(pipe_path)
    else:
        assert config_writer is not None
        config_writer(process_config)
    if DEBUG_LAUNCH:
        try:
            debug_tmp = Path("tmp")
            debug_tmp.mkdir(parents=True, exist_ok=True)
            run_sh = debug_tmp / "run.sh"
            run_sh.write_text(
                "#!/bin/bash\n"
                + cmd[0]
                + " "
                + " \\\n  ".join(param if " " not in param else repr(param) for param in cmd[1:])
                + "\n"
            )
            logger.debug("DEBUG_LAUNCH: wrote %s", run_sh.resolve())
        except:  # noqa: E722
            logger.debug("Can not write run.sh")
    try:

        def preexec_fn() -> None:
            if extra_preexec_fn:
                extra_preexec_fn()
            os.umask(0o006)  # Only user:RW

        logger.debug("Start process: " + " ".join((repr(c) if " " in c else c for c in cmd)))
        subprocess_kwargs: dict[str, Any] = dict(
            env=dict(envs),
            preexec_fn=preexec_fn,
        )
        if pass_fds:
            subprocess_kwargs["pass_fds"] = pass_fds
        if stdout is not None:
            subprocess_kwargs["stdout"] = stdout
        if stderr is not None:
            subprocess_kwargs["stderr"] = stderr
        if stdin is not None:
            subprocess_kwargs["stdin"] = stdin

        process = await asyncio.create_subprocess_exec(
            *cmd,
            **subprocess_kwargs,
        )

        # Notify caller before blocking on FIFO write (e.g., to start slirp4netns)
        if on_launched and process.pid is not None:
            on_launched(process.pid)

        # It's a good time for that
        gc.collect()
        if use_fifo:
            with os.fdopen(await _open_fifo_for_write(pipe_path, process), "wb") as fifo:
                # serialization only
                fifo.write(pickle.dumps(process_config))
                fifo.flush()
            pipe_path.unlink()
        return process
    finally:
        pass


def find_free_port() -> int:
    """Find and return an available TCP port.

    Returns:
        Number of a free TCP port.

    Raises:
        RuntimeError: If no free port could be found.
    """
    # Use contextlib.closing to ensure the socket is properly closed
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            # The port number 0 tells the OS to find an ephemeral port
            s.bind(("", 0))
            # Set SO_REUSEADDR option to allow reuse of the address
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Return the port number assigned by the OS
            return s.getsockname()[1]
    except socket.error as e:
        raise RuntimeError(f"Impossible to finding a free port: {e}") from e


class BaseSubProcessDaemon(BaseSSESandbox):
    """Base class for subprocess-based sandbox daemons.

    Manages subprocess lifecycle including automatic restart on failure,
    watchdog monitoring, and communication via SSE over HTTP.
    """

    __slots__ = (
        "_is_started",
        "_token",
        "_process",
        "_watchdog",
        "_attempts",
        "_base_delay",
        "_factor",
        "_max_delay",
        "_max_attempts",
        "_reset_delay",
        "_last_reset",
        "_is_started",
        "_python_args",
        "restart",
    )

    async def _on_process_started(self) -> None:
        """Hook called after the subprocess is started but before the ping loop."""

    def _ping_url(self, port: int) -> str:
        """HTTP URL used to wait until the sandbox daemon accepts connections."""
        return f"http://127.0.0.1:{port}/ping"

    def __init__(
        self,
        token: str,
        *,
        host: str = "localhost",
        python_args: list[str] | None = None,
        max_connect_retry: int = MAX_CONNECT_RETRY,
        max_attempts: int = RETRY_MAX_ATTEMPTS,
        # Maximum number of retry _attempts
        base_delay: float = RETRY_BASE_DELAY,
        # Initial delay in seconds (e.g., 100 ms)
        factor: float = RETRY_FACTOR,  # Exponential increase _factor
        max_delay: float = RETRY_MAX_DELAY,  # Maximum delay in seconds
        reset_delay: float = RETRY_RESET_DELAY,  # delay to reset attempts
    ) -> None:
        """Initialize the subprocess daemon.

        Args:
            token: Authentication token for communication.
            host: Host address for communication.
            python_args: Additional Python arguments for subprocess.
            max_connect_retry: Maximum connection retry attempts.
            max_attempts: Maximum restart attempts before giving up.
            base_delay: Initial delay between restart attempts.
            factor: Exponential backoff factor for delays.
            max_delay: Maximum delay between attempts.
            reset_delay: Delay after which attempt counter resets.
        """
        super().__init__(token, max_connect_retry=max_connect_retry)
        self._python_args = python_args or []
        self._process: Process | None = None
        self._watchdog: Task | None = None
        self._attempts = 0
        self._base_delay = base_delay
        self._factor = factor
        self._max_delay = max_delay
        self._max_attempts = max_attempts
        self._reset_delay = reset_delay
        self._last_reset = time.time()
        self._is_started = False
        self.restart = 0

    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Build command line arguments for subprocess.

        Args:
            all_rules: Security rules configuration.
            envs: Environment variables.
            pipe_path: Path to named pipe for configuration.

        Returns:
            List of command line arguments.
        """
        from . import main_sandbox

        cmd_parameters = [
            sys.executable,
            "-u",  # Unbuffered output
        ]
        if sys.flags.optimize:
            cmd_parameters.append("-" + "O" * sys.flags.optimize)
        cmd_parameters.extend(self._python_args)
        cmd_parameters.extend(
            [
                "-m",
                main_sandbox.__name__,
            ]
        )
        return cmd_parameters, {}

    async def _start(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        """Start the subprocess daemon.

        Args:
            all_rules: Security rules configuration.
            envs: Environment variables.
            log_level: Logging level to set.
            init_fn: Optional initialization function.
        """
        self.restart = 0
        self.port = find_free_port() if all_rules.port == -1 else all_rules.port

        await self._re_start(
            all_rules,
            envs=envs,
            log_level=log_level,
            init_fn=init_fn,
            first=True,
        )
        self._watchdog = asyncio.create_task(
            self.watchdog(all_rules, envs=envs, log_level=log_level, init_fn=init_fn),
            name="ControlDaemon",
        )

    async def watchdog(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        """Monitor subprocess and restart on failure.

        Args:
            all_rules: Security rules configuration.
            envs: Environment variables.
            log_level: Logging level.
            init_fn: Optional initialization function.
        """
        errorlevel = -1
        if self._process is None:
            return
        try:
            self._attempts = 0
            while errorlevel != 0:
                errorlevel = await self._process.wait()
                # Process is dead
                if not self._accept_incoming:
                    break  # Detect legitimate _shutdown

                if errorlevel != 0:
                    logger.info("watchdog: subprocess exited with %s", errorlevel)
                    if time.time() - self._last_reset > self._reset_delay:
                        self._attempts = 0
                    self._attempts += 1
                    if self._attempts > self._max_attempts:
                        import os

                        logger.error("Too many daemon shutdowns")
                        os._exit(-2)
                    # Calculate the base delay for this attempt
                    current_base_backoff: float = min(
                        self._max_delay,
                        self._base_delay * (self._factor ** (self._attempts - 1)),
                    )

                    wait_time: float = random.uniform(current_base_backoff * 0.9, current_base_backoff)
                    logger.debug("watchdog sleep %i", wait_time)
                    await asyncio.sleep(wait_time)
                    # await self._shutdown()
                    self._last_reset = time.time()
                    await self._re_start(all_rules, envs=envs, log_level=log_level, init_fn=init_fn)
        except CancelledError:
            pass  # Ignore

    async def _re_start(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
        first: bool = False,
    ) -> None:
        """Restart the subprocess daemon.

        Args:
            all_rules: Security rules configuration.
            envs: Environment variables.
            log_level: Logging level.
            init_fn: Optional initialization function.
            first: Whether this is the first start (not a restart).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            pipe_path = Path(tmpdir) / f"_{uuid.uuid4().hex}"
            pipe_path.unlink(missing_ok=True)
            from ..guard_socket import parse_rules as socket_parse_rules

            # Add rules for the communication with the sandbox
            socket_rules: list[SocketRule] = list(all_rules.socket_rules)
            _new_socket_rules, *_ = socket_parse_rules([ConfigLine(f"net=ALLOW|TCP|*|{self.port}|IN", Path(), 0)], [])
            socket_rules.extend(_new_socket_rules)

            from pysandboxes.guard_socket import SocketRules

            all_rules = all_rules._replace(socket_rules=SocketRules(socket_rules))

            cmds, env = self.subprocess_cmd(
                all_rules=all_rules,
                envs=envs,
                pipe_path=pipe_path,
                temp=Path(tmpdir),
            )

            await self._re_start_cmd(
                all_rules,
                cmds,
                env,
                pipe_path=pipe_path,
                port=self.port,
                log_level=log_level,
                init_fn=init_fn,
            )

        if first:
            pysandboxes_logger.info("Daemon Sandbox started")
        else:
            pysandboxes_logger.warning("Daemon Sandbox re-started")

    async def _re_start_cmd(
        self,
        all_rules: AllRules,
        args: Args,
        extra_envs: Environ,
        pipe_path: Path,
        port: int,
        *,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        """Execute subprocess restart with given command and configuration.

        Args:
            all_rules: Security rules configuration.
            args: Command line arguments for subprocess.
            pipe_path: Path to named pipe for configuration.
            port: Network port for communication.
            log_level: Logging level.
            init_fn: Optional initialization function.
        """
        self._is_started = False
        self._accept_incoming = False
        if init_fn:
            module, init_function_reference = get_callable_info(init_fn)
            init_fn_ref = f"{module}:{init_function_reference}"
        else:
            init_fn_ref = ""

        process_config = DaemonParameters(
            all_rules=all_rules,
            log_level=log_level,
            log_format=get_log_formatter(),
            use_rich_handler=use_rich_handler(),
            token=self._token,
            port=port,
            init_fn=init_fn_ref,
        )

        env: Environ
        if all_rules.learn:
            env = {**os.environ, **all_rules.envs}
        else:
            env = dict(all_rules.envs)
        env = {**os.environ, **extra_envs}
        logger.debug("Launch process:" + " ".join((repr(c) if " " in c else c for c in args)))
        self._process = await launch_sandbox(
            args + ["--_named-pipe", str(pipe_path)],
            pipe_path=pipe_path,
            envs=Envs(env),
            process_config=process_config,
        )
        logger.info(
            "Subprocess launched (pid=%s), waiting for daemon (ping URL resolved each attempt)",
            self._process.pid,
        )
        try:
            await self._on_process_started()
        except Exception:  # noqa: BLE001
            raise
        # Wait the server
        gc.collect()
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector) as session:
            count_loop = 0
            while True:
                try:
                    count_loop += 1
                    ping_url = self._ping_url(port)
                    if count_loop == 1:
                        logger.info("Pinging subprocess daemon at %s", ping_url)
                    if count_loop > LOOP_FOR_PING:
                        logger.error(
                            "Is not possible to connect " "to the sandbox daemon (%s)",
                            ping_url,
                        )
                        raise SystemExit(-1)
                    async with session.get(
                        ping_url,
                        timeout=ClientTimeout(
                            total=TIMEOUT_FOR_PING,
                        ),
                    ) as response:
                        if response.status == 200:
                            break
                        else:
                            raise RuntimeError(f"Unexpected status {response.status} from {ping_url}")
                except TimeoutError:
                    if count_loop % 15 == 0:
                        logger.info(
                            "Ping attempt %d/%d: timeout (subprocess not ready yet?)",
                            count_loop,
                            LOOP_FOR_PING,
                        )
                except (ClientConnectorError, ServerDisconnectedError) as e:
                    if count_loop % 15 == 0:
                        logger.info(
                            "Ping attempt %d/%d: %s",
                            count_loop,
                            LOOP_FOR_PING,
                            type(e).__name__,
                        )
                except ClientOSError as e:
                    if not is_transient_connection_error(e):
                        raise
                    if count_loop % 15 == 0:
                        logger.info(
                            "Ping attempt %d/%d: %s",
                            count_loop,
                            LOOP_FOR_PING,
                            type(e).__name__,
                        )

                await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)

        # One more time
        await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)
        logger.info("Subprocess daemon is up and running at %s", ping_url)
        self._is_started = True
        self._accept_incoming = True

    async def _stop(self, max_pending: int) -> None:
        """Stop the subprocess daemon.

        Args:
            max_pending: Maximum pending operations to wait for.
        """
        if self._watchdog:
            self._watchdog.cancel()
            self._watchdog = None

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        """Shutdown the subprocess daemon.

        Args:
            graceful_shutdown: Whether to perform graceful shutdown.
        """
        await super()._shutdown(graceful_shutdown)
        self.max_connect_retry = 1  # Try only one time for remote _shutdown

        logger.debug("Call remote daemon_shutdown...")
        try:
            await self.async_call_in_sandbox(
                main_shutdown.daemon_shutdown,  # Call remote sandbox daemon_shutdown
                True,
                graceful_shutdown,
            )
            logger.debug("Call remote daemon_shutdown done")
            if graceful_shutdown:
                if self._process:
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=TIMEOUT_FOR_STOP_DAEMON)
                    except asyncio.TimeoutError:
                        logger.warning("Kill the sandbox daemon")
                        self._process.kill()
                    logger.debug("Sandbox daemon is terminated")
                    self._process = None
            else:
                logger.info("Kill the sandbox daemon (graceful_shutdown=%s)", graceful_shutdown)
                if self._process:
                    self._process.kill()
        except OSError:
            pass
        except (SystemExit, KeyboardInterrupt):
            raise
        except RuntimeError:
            pass  # Ignore
        except Exception as e:
            logger.exception("Unknown error in _shutdown")
            assert e is None, f"Unknown error in _shutdown {e}"
        finally:
            self._process = None
            self._is_started = False

    def on_process_launched(self, process_pid: int) -> None:
        pass

    def get_launch_extras(self) -> tuple[Any, tuple[int, ...]]:
        return None, ()


class SubProcessDaemon(BaseSubProcessDaemon):
    """Standard subprocess daemon implementation.

    Simple subprocess daemon that delegates rule updates to the parent class.
    """

    def update_rules_and_activate(
        self,
        *,
        envs: Envs,
        all_rules: AllRules,
        temp: Path,
    ) -> AllRules:
        """Update security rules (no-op for basic subprocess daemon).

        Args:
            envs: Environment variables.
            all_rules: Current security rules.

        Returns:
            Unchanged security rules.
        """
        return all_rules
