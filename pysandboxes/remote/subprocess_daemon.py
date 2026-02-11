import asyncio
import gc
import logging
import os
import pickle
import random
import sys
import tempfile
import time
import uuid
from asyncio.subprocess import Process
from pathlib import Path
from typing import Callable, Optional, NamedTuple, List

import aiohttp
from aiohttp import ClientConnectorError

from . import main_shutdown
from .parameters import INTERVAL_FOR_PING_DAEMON, RETRY_RESET_DELAY, RETRY_MAX_DELAY, \
    RETRY_FACTOR, RETRY_BASE_DELAY, RETRY_MAX_ATTEMPTS
from .sse_sandbox import SSESandbox, PING_SERVER_URL
from ..all_rules import AllRules
from ..main_logger import pysandboxes_logger
from ..sb_types import Args, Envs
from ..tools import SyncOrAsyncFunc, get_callable_info

logger = logging.getLogger(__name__)


def get_log_formatter():
    root_logger = logging.getLogger()
    fmt = None
    for h in root_logger.handlers:
        fmt = h.formatter
        break
    if fmt is None:
        # Default formatter if none set explicitly
        fmt = logging.Formatter()
    return fmt._fmt


async def _write_stream(
        child_stdin_writer: asyncio.StreamWriter
) -> None:
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
                child_stdin_writer.write(line.encode('utf-8'))
                await child_stdin_writer.drain()
            except Exception as e:
                break
    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
        if master_fd:
            os.close(master_fd)


async def _read_stream(
        stream: asyncio.StreamReader,
        callback: Callable[[str], None]) -> None:
    while True:
        line: bytes = await stream.readline()
        if line:
            callback(line.decode('utf-8').strip())
        else:
            break


class DaemonParameters(NamedTuple):
    all_rules: AllRules
    log_level: int
    log_format: str
    token: str
    init_fn: str


async def launch_sandbox(
        cmd: List[str],
        pipe_path: Path,
        envs: Envs,
        process_config: DaemonParameters,
) -> Process:
    os.mkfifo(pipe_path)
    if False:
        Path("run.sh").write_text("#!/bin/bash\n" +  # FIXME: create run.sh to debug
                                  cmd[0] + " " +
                                  " \\\n  ".join(
                                      param if " " not in param else repr(param) for
                                      param in cmd[1:]) +
                                  "\n")
    try:
        def preexec_fn():
            os.umask(0o006)  # Only user:RW

        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=dict(envs),
            preexec_fn=preexec_fn
        )

        # It's a good time for that
        gc.collect()
        with open(pipe_path, 'wb') as fifo:
            fifo.write(pickle.dumps(process_config))
            fifo.close()
        pipe_path.unlink()
        return process
    finally:
        pass


class BaseSubProcessDaemon(SSESandbox):
    __slots__ = ('_is_started', '_token',
                 '_process',
                 '_attempts',
                 '_base_delay',
                 '_factor',
                 '_max_delay',
                 '_max_attempts',
                 '_reset_delay',
                 '_last_reset',
                 '_is_started'
                 'restart',
                 )

    def __init__(self,
                 token: str,
                 *,
                 python_args: Optional[List[str]] = None,
                 max_attempts: int = RETRY_MAX_ATTEMPTS,
                 # Maximum number of retry _attempts
                 base_delay: float = RETRY_BASE_DELAY,
                 # Initial delay in seconds (e.g., 100 ms)
                 factor: float = RETRY_FACTOR,  # Exponential increase _factor
                 max_delay: float = RETRY_MAX_DELAY,  # Maximum delay in seconds
                 reset_delay: float = RETRY_RESET_DELAY,  # delay to reset attemps
                 **kwargs,
                 ):
        super().__init__(token)
        self._python_args = python_args or []
        self._process = None
        self._attempts = 0
        self._base_delay = base_delay
        self._factor = factor
        self._max_delay = max_delay
        self._max_attempts = max_attempts
        self._reset_delay = reset_delay
        self._last_reset = time.time()
        self._is_started = False
        self.restart = 0

    def subprocess_cmd(self,
                       all_rules: AllRules,
                       ) -> Args:
        from . import main_sandbox
        cmd_parameters = [
            sys.executable,
            # don't prepend a potentially unsafe path to sys.path; also PYTHONSAFEPATH
            # "-m", "pdb",
            "-P",
            "-u",  # Unbuffered output
            "-d",  # Mode debug à la sortie
            # "-X","importtime", # FIXME
            # "-B", # FIXME: no pyc
            # "-v", # FIXME
        ]
        cmd_parameters.extend(self._python_args)
        cmd_parameters.extend([
            "-m",
            main_sandbox.__name__,
        ])
        return cmd_parameters

    async def start(self,
                    all_rules: AllRules,
                    *,
                    log_level: int,
                    init_fn: Optional[SyncOrAsyncFunc],
                    ) -> None:
        self.restart = 0
        await self._re_start(all_rules,
                             log_level=log_level,
                             init_fn=init_fn,
                             first=True,
                             )

    async def _re_start(self,
                        all_rules: AllRules,
                        *,
                        log_level: int,
                        init_fn: Optional[SyncOrAsyncFunc],
                        first: bool = False) -> None:
        if first:
            short_all_rules = AllRules(  # TODO: why short copy of AllRules?
                config=all_rules.config,
                envs=all_rules.envs,
                os_sandbox=all_rules.os_sandbox,
                use_py_sandbox=all_rules.use_py_sandbox,
                learning_path=all_rules.learning_path,
                learn=all_rules.learn,
                envs_rules=(),
                socket_rules=(),
                file_rules=(),
                import_rules=(),  # all_rules.import_rules,
            )
            await self._re_start_cmd(
                all_rules,
                self.subprocess_cmd(
                    all_rules=short_all_rules,
                ),
                log_level=log_level,
                init_fn=init_fn,
            )

            pysandboxes_logger.info("started")
        else:
            pysandboxes_logger.warning("re-started")

    async def _re_start_cmd(self,
                            all_rules: AllRules,
                            args: Args,
                            *,
                            log_level: int,
                            init_fn: Optional[SyncOrAsyncFunc],
                            ) -> None:
        self._is_started = False

        with tempfile.TemporaryDirectory() as tmpdir:
            pipe_path = Path(tmpdir) / f"_{uuid.uuid4().hex}"
            pipe_path.unlink(missing_ok=True)

            if init_fn:
                module, init_function_reference = get_callable_info(init_fn)
                init_fn_ref = f"{module}:{init_function_reference}"
            else:
                init_fn_ref = ""

            process_config = DaemonParameters(
                all_rules=all_rules,
                log_level=log_level,
                log_format=get_log_formatter(),
                token=self._token,
                init_fn=init_fn_ref
            )

            if all_rules.learn:
                env = {**os.environ, **all_rules.envs}
            else:
                env = all_rules.envs

            self._process = await launch_sandbox(
                args + ["--_named-pipe", str(pipe_path)],
                pipe_path=pipe_path,
                envs=Envs(env),
                process_config=process_config,
            )

            # Wait the server
            gc.collect()
            async with aiohttp.ClientSession() as session:
                while True:
                    try:  # TODO: test in the server never response
                        async with session.get(
                                PING_SERVER_URL,
                                timeout=INTERVAL_FOR_PING_DAEMON) as response:
                            if response.status == 200:
                                break
                            else:
                                raise RuntimeError(
                                    f"Unexpected status {response.status} from {PING_SERVER_URL}")
                    except ClientConnectorError:
                        pass  # Ignore and continue

                    await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)

            self._is_started = True

    async def shutdown(self) -> None:
        await self.async_call_in_sandbox(
            main_shutdown.shutdown,
        )
        if self._process:
            if self._process.returncode is None:
                # Child process receive SIGINT
                self._process.terminate()
                await self._process.wait()
            self._process = None
        self._is_started = False
        logger.debug("shutdown")

    async def join(self) -> int:  # FIXME: utilisé ? Utilisable ?
        errorlevel = -1
        while errorlevel != 0:
            errorlevel = await self._process.wait()
            if errorlevel != 0:
                logger.warning("subprocess exited with %s", errorlevel)
                if time.time() - self._last_reset > self._reset_delay:
                    self._attempts = 0
                self._attempts += 1
                if self._attempts > self._max_attempts:
                    return errorlevel
                # Calculate the base delay for this attempt
                current_base_backoff: float = min(self._max_delay,
                                                  self._base_delay * (
                                                          self._factor ** (
                                                          self._attempts - 1)))

                wait_time: float = random.uniform(current_base_backoff * 0.9,
                                                  current_base_backoff)
                await asyncio.sleep(wait_time)
                await self.shutdown()
                self._last_reset = time.time()
                await self._re_start()  # FIXME: mauvais parametres
        return errorlevel


class SubProcessDaemon(BaseSubProcessDaemon):

    def update_rules(self,
                     *,
                     envs: Envs,
                     all_rules: AllRules,
                     ) -> AllRules:
        return all_rules
