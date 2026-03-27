# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Subprocess-based daemon client for PySandboxes remote execution.

This module implements a subprocess-based daemon that spawns isolated Python
processes for sandboxed code execution. It provides process management,
watchdog functionality, and IPC communication via Server-Sent Events (SSE).

Key components:
- BaseSubProcessDaemon: Base class for subprocess-based sandboxes
- SubProcessDaemon: Standard subprocess implementation
- DaemonParameters: Configuration data structure
- Process lifecycle management with automatic restart on failure
"""

import asyncio
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
from typing import Callable, NamedTuple

import aiohttp
from aiohttp import ClientConnectorError, ClientTimeout

from ..all_rules import AllRules
from ..guard_socket import SocketRule
from ..main_logger import pysandboxes_logger
from ..private_loop import sandbox_loop
from ..sb_types import Args, ConfigLine, Envs
from ..tools import Environ, SyncOrAsyncFunc, get_callable_info
from . import main_shutdown
from .parameters import (
    INTERVAL_FOR_PING_DAEMON,
    LOOP_FOR_PING,
    MAX_CONNECT_RETRY,
    RETRY_BASE_DELAY,
    RETRY_FACTOR,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_DELAY,
    RETRY_RESET_DELAY,
    TIMEOUT_FOR_PING,
    TIMEOUT_FOR_STOP_DAEMON,
)
from .sse_base_daemon import BaseSSESandbox

logger = logging.getLogger(__name__)

DEBUG_LAUNCH = True  # FIX_RELEASE


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


async def _read_stream(
    stream: asyncio.StreamReader, callback: Callable[[str], None]
) -> None:
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


class DaemonParameters(NamedTuple):
    """Configuration parameters for daemon processes.
    To assist in scenarios where there is no sandbox initialization function, we propagate the main log
    parameters as default behavior.
    Attributes:
        all_rules: Security rules configuration.
        log_level: Logging level for the daemon.
        log_format: Format string for log messages.
        use_rich_handler: Use Rich Handler
        token: Authentication token for communication.
        port: Network port for communication.
        init_fn: Initialization function reference.
    """

    all_rules: AllRules
    log_level: int
    log_format: str
    use_rich_handler: bool
    token: str
    port: int
    init_fn: str


@sandbox_loop
async def launch_sandbox(
    cmd: list[str],
    pipe_path: Path,
    envs: Envs,
    process_config: DaemonParameters,
) -> Process:
    """Launch a sandbox subprocess with the given configuration.

    Args:
        cmd: Command line arguments for the subprocess.
        pipe_path: Path to named pipe for configuration transfer.
        envs: Environment variables for the subprocess.
        process_config: Configuration parameters to send to subprocess.

    Returns:
        The launched subprocess.
    """
    os.mkfifo(pipe_path)
    if DEBUG_LAUNCH:
        try:
            Path("run.sh").write_text(
                "#!/bin/bash\n"
                + cmd[0]
                + " "
                + " \\\n  ".join(
                    param if " " not in param else repr(param) for param in cmd[1:]
                )
                + "\n"
            )
        except:  # noqa: E722
            logger.debug("Can not write run.sh")
    try:

        def preexec_fn() -> None:
            os.umask(0o006)  # Only user:RW

        logger.debug(
            "Start process: " + " ".join((repr(c) if " " in c else c for c in cmd))
        )
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=dict(envs),
            preexec_fn=preexec_fn,
        )

        # It's a good time for that
        gc.collect()
        with open(pipe_path, "wb") as fifo:
            fifo.write(pickle.dumps(process_config))
            fifo.flush()
            fifo.close()
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
        pass

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
    ) -> Args:
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
        if sys.version_info[:2] >= (3, 11):
            cmd_parameters.append(
                "-P"
            )  # Don't prepend a potentially unsafe path to sys.path; also PYTHONSAFEPATH
        if sys.flags.optimize:
            cmd_parameters.append("-" + "O" * sys.flags.optimize)
        cmd_parameters.extend(self._python_args)
        cmd_parameters.extend(
            [
                "-m",
                main_sandbox.__name__,
            ]
        )
        return cmd_parameters

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

                        logger.error("Too many demon shutdowns")
                        os._exit(-2)
                    # Calculate the base delay for this attempt
                    current_base_backoff: float = min(
                        self._max_delay,
                        self._base_delay * (self._factor ** (self._attempts - 1)),
                    )

                    wait_time: float = random.uniform(
                        current_base_backoff * 0.9, current_base_backoff
                    )
                    logger.debug("watchdog sleep %i", wait_time)
                    await asyncio.sleep(wait_time)
                    # await self._shutdown()
                    self._last_reset = time.time()
                    await self._re_start(
                        all_rules, envs=envs, log_level=log_level, init_fn=init_fn
                    )
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
            _new_socket_rules, *_ = socket_parse_rules(
                [ConfigLine(f"net=ALLOW|TCP|*|{self.port}|IN", Path(), 0)], []
            )
            socket_rules.extend(_new_socket_rules)

            from pysandboxes.guard_socket import SocketRules

            all_rules = all_rules._replace(socket_rules=SocketRules(socket_rules))

            await self._re_start_cmd(
                all_rules,
                self.subprocess_cmd(
                    all_rules=all_rules,
                    envs=envs,
                    pipe_path=pipe_path,
                    temp=Path(tmpdir),
                ),
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

        logger.debug(
            "Launch process:" + " ".join((repr(c) if " " in c else c for c in args))
        )
        self._process = await launch_sandbox(
            args + ["--_named-pipe", str(pipe_path)],
            pipe_path=pipe_path,
            envs=Envs(env),
            process_config=process_config,
        )

        await self._on_process_started()

        # Wait the server
        gc.collect()
        ping_url = self.base_url.replace("{PORT}", str(port)) + "/ping"
        logger.debug("Try to call %s", ping_url)
        async with aiohttp.ClientSession() as session:
            count_loop = 0
            while True:
                try:
                    count_loop += 1
                    if count_loop > LOOP_FOR_PING:
                        logger.error("Is not possible to connect to the sandbox daemon")
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
                            raise RuntimeError(
                                f"Unexpected status {response.status} from {ping_url}"
                            )
                except TimeoutError:
                    pass  # Ignore and continue
                except ClientConnectorError:
                    pass  # Ignore and continue

                await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)

        # One more time
        await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)
        logger.debug("Sandbox daemon is up and running")
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
                        await asyncio.wait_for(
                            self._process.wait(), timeout=TIMEOUT_FOR_STOP_DAEMON
                        )
                    except asyncio.TimeoutError:
                        logger.warning("Kill the sandbox daemon")
                        self._process.kill()
                    logger.debug("Sandbox daemon is terminated")
                    self._process = None
            else:
                logger.info(
                    "Kill the sandbox daemon (graceful_shutdown=%s)", graceful_shutdown
                )
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


class SubProcessDaemon(BaseSubProcessDaemon):
    """Standard subprocess daemon implementation.

    Simple subprocess daemon that delegates rule updates to the parent class.
    """

    def update_rules(
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
