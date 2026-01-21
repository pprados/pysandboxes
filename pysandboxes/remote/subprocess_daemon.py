import asyncio
import logging
import os
import random
import sys
import time
from abc import abstractmethod
from pathlib import Path
from typing import Callable, Dict, Any, Optional, NamedTuple

from .parameters import DELAY_FOR_START_DAEMON
from .sse_sandbox import SSESandbox
from .tools import to_b85
from ..main_logger import pysandboxes_logger
from ..py_sandbox import AllRules, parse_config
from ..tools import SyncOrAsyncFunc, get_callable_info
from ..types import ConfigLines, Args, Envs

logger = logging.getLogger(__name__)

DEBUG = False


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


class SubProcessParameters(NamedTuple):
    all_rules: AllRules
    log_level: int
    token: str
    init_fn: str


class BaseSubProcessDaemon(SSESandbox):
    __slots__ = ('_is_started', '_token',
                 '_process',
                 '_stdout_task',
                 '_stderr_task',
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
                 max_attempts: int = 1,  # Maximum number of retry _attempts TODO 5
                 base_delay: float = 0.1,  # Initial delay in seconds (e.g., 100 ms)
                 factor: float = 2.0,  # Exponential increase _factor
                 max_delay: float = 10.0,  # Maximum delay in seconds
                 reset_delay: float = 120.0  # delay to reset attemps
                 ):
        super().__init__(token)
        self._process = None
        self._stdout_task = None
        self._stderr_task = None
        self._attempts = 0
        self._base_delay = base_delay
        self._factor = factor
        self._max_delay = max_delay
        self._max_attempts = max_attempts
        self._reset_delay = reset_delay
        self._last_reset = time.time()
        self._is_started = False
        self.restart = 0

    def _subprocess(self,
                    all_rules: AllRules,
                    envs: Envs,
                    ) -> Args:
        from . import run_daemon
        cmd_parameters = [
            sys.executable,
            # don't prepend a potentially unsafe path to sys.path; also PYTHONSAFEPATH
            "-P",

            "-u",  # FIXME unbuffered stdout and stderr?
            "-m",
            run_daemon.__name__,
        ]
        return cmd_parameters

    @abstractmethod
    def bash_args(self, envs: Envs) -> Args:
        pass

    async def start(self,
                    all_rules: AllRules,
                    *,
                    log_level: int,
                    envs: Envs,
                    init_fn: Optional[SyncOrAsyncFunc],
                    ) -> None:
        if not envs:
            envs = dict(os.environ)
        self.restart = 0
        await self._re_start(all_rules,
                             envs=envs,
                             log_level=log_level,
                             init_fn=init_fn,
                             first=True,
                             )

    async def _re_start(self,
                        all_rules: AllRules,
                        *,
                        envs: Envs,
                        log_level: int,
                        init_fn: Optional[SyncOrAsyncFunc],
                        first: bool = False) -> None:
        if first:
            short_all_rules = AllRules(
                config=all_rules.config,
                envs=all_rules.envs,
                os_sandbox=all_rules.os_sandbox,
                use_py_sandbox=all_rules.use_py_sandbox,
                socker_rules=[],
                file_rules=[],
            )

            await self._re_start_cmd(
                short_all_rules,
                self._subprocess(
                    all_rules=short_all_rules,
                    envs=envs,
                ), {},
                log_level=log_level,
                init_fn=init_fn,
            )

            pysandboxes_logger.info("started")
        else:
            pysandboxes_logger.warning("re-started")

    async def _re_start_cmd(self,
                            all_rules: AllRules,
                            args: Args,
                            process_kwargs: Dict[str, Any],
                            *,
                            log_level: int,
                            init_fn: Optional[SyncOrAsyncFunc],
                            stdin: bool = False,
                            stdout: bool = False) -> None:
        self._is_started = False

        umask = os.umask(0o002)
        umask = os.umask(umask) & 0o007  # Only keep user flags

        if DEBUG:
            Path("run.sh").write_text("#!/bin/bash\n" +  # FIXME:
                                      args[0] + " " +
                                      " \\\n  ".join(
                                          param if " " not in param else repr(param) for
                                          param in args[1:]) +
                                      "\n")

        self._process = await asyncio.create_subprocess_exec(
            *args,
            **process_kwargs,
            # FIXME: avec ceci, il n'y a plus de trace sur la console
            # Voir comment fixer cela.
            stdout=asyncio.subprocess.PIPE,
            # stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE,

            # close_fds=True,
            # cwd=None,
            # restore_signals=True,
            # #     # process_group=1,  # FIXME
            umask=umask,
            env=os.environ.copy(),
        )

        # Send config body via stdin, because, it's not possible to use .py-sandboxes file

        module, init_function_reference = get_callable_info(init_fn)

        process_config = SubProcessParameters(
            all_rules=all_rules,
            log_level=log_level,
            token=self._token,
            init_fn=f"{module}:{init_function_reference}"
        )
        data = to_b85(process_config) + "\n"

        self._process.stdin.write(data.encode("utf-8"))
        await self._process.stdin.drain()
        if stdin:
            self._stdin_task = asyncio.create_task(
                _write_stream(
                    self._process.stdin
                ),
                name="write_stream",
            )
        if stdout:
            self._stdout_task = asyncio.create_task(
                _read_stream(
                    self._process.stdout,
                    lambda line: print(line, file=sys.stdout, flush=True)
                ),
                name="read_stdout_stream",
            )
            self._stderr_task = asyncio.create_task(
                _read_stream(
                    self._process.stderr,
                    lambda line: print(line, file=sys.stderr, flush=True)
                ),
                name="read_stderr_stream"
            )
        await asyncio.sleep(DELAY_FOR_START_DAEMON)
        # FIXME: detecter le start effectif par une boucle de connexion ?
        self._is_started = True

    async def shutdown(self) -> None:
        if self._stdout_task:
            self._stdout_task.cancel()
            self._stdout_task = None
        if self._stderr_task:
            self._stderr_task.cancel()
            self._stderr_task = None
        if self._process:
            if self._process.returncode is None:
                # Child process receive SIGINT
                self._process.terminate()
                await self._process.wait()
            self._process = None
        self._is_started = False
        pysandboxes_logger.info("shutdown")

    async def join(self) -> int:
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
                current_base_backoff: float = min(self._max_delay, self._base_delay * (
                        self._factor ** (self._attempts - 1)))

                wait_time: float = random.uniform(current_base_backoff * 0.9,
                                                  current_base_backoff)
                await asyncio.sleep(wait_time)
                await self.shutdown()
                self._last_reset = time.time()
                await self._re_start()
        return errorlevel

    # def convert_rules(self, socket_rules: AllRules) -> AllRules:
    #     return socket_rules


class SubProcessDaemon(BaseSubProcessDaemon):

    def update_rules(self,
                     *,
                     envs: Envs,
                     config: ConfigLines) -> AllRules:
        return parse_config(envs=envs, config=config, exit_on_error=True)

    def bash_args(self, envs: Envs) -> Args:
        return ["/bin/bash",
                "-c",
                "PS1='[os-sandbox-subprocess] $ '; "
                "export PS1; "
                "exec /bin/bash --norc --noprofile -i"], {}
