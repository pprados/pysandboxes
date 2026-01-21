import asyncio
import logging
import os
import random
import sys
import time
import uuid
from abc import abstractmethod
from pathlib import Path
from typing import Callable, Dict, Any, Optional

from .sse_sandbox import SSESandbox
from .tools import return_level_parameter, to_b85
from ..py_sandbox import AllRules, read_and_parse_config
from ..tools import SyncOrAsyncFunc, get_callable_info
from ..types import ConfigLines, Args, Envs

logger = logging.getLogger(__name__)

DEBUG = True


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


class BaseSubProcessDaemon(SSESandbox):

    def __init__(self,
                 max_attempts: int = 1,  # Maximum number of retry _attempts TODO 5
                 base_delay: float = 0.1,  # Initial delay in seconds (e.g., 100 ms)
                 factor: float = 2.0,  # Exponential increase _factor
                 max_delay: float = 10.0,  # Maximum delay in seconds
                 reset_delay: float = 120.0  # delay to reset attemps
                 ):
        super().__init__()
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
        self.restart = 0
        self._is_started = False

    def _subprocess(self,
                    envs: Dict[str, str],
                    log_level: int,
                    init_fn: Optional[SyncOrAsyncFunc],
                    config: ConfigLines,
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
        verbose = return_level_parameter(log_level)
        if verbose:
            cmd_parameters.append(verbose)
        if init_fn:
            module, init_function_reference = get_callable_info(init_fn)
            cmd_parameters.extend(
                ["--init-function", f"{module}:{init_function_reference}"])

        return cmd_parameters

    @abstractmethod
    def bash_args(self, envs: Envs) -> Args:
        pass

    async def start(self, log_level: int,
                    envs: Envs,
                    config: ConfigLines,
                    init_fn: Optional[SyncOrAsyncFunc],
                    token: str) -> None:
        if not envs:
            envs = dict(os.environ)
        self.restart = 0
        await self._re_start(envs,
                             log_level,
                             config,
                             init_fn,
                             token=token,
                             first=True,
                             )

    async def _re_start(self,
                        envs: Envs,
                        log_level: int,
                        config: ConfigLines,
                        init_fn: Optional[SyncOrAsyncFunc],
                        *,
                        token: str,
                        first: bool = False) -> None:
        if first:
            await self._re_start_cmd(self._subprocess(
                envs,
                log_level,
                init_fn,
                config,
            ), {},
                config=config,
            )

            logger.info("daemon is started")
        else:
            logger.warning("daemon is re-started")

    async def _re_start_cmd(self,
                            args: Args,
                            process_kwargs: Dict[str, Any],
                            *,
                            config: ConfigLines,
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
        self._token = str(uuid.uuid4())

        data = to_b85((config, self._token)) + "\n"

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
        # FIXME self.task = asyncio.create_task(self.daemon.serve())
        self._is_started = True  # FIXME: detecter le start

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
        logger.info("daemon is shutdown")

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
    def _subprocess(self,
                    envs: Dict[str, str],
                    log_level: int,
                    init_fn: Optional[SyncOrAsyncFunc],
                    config: ConfigLines,
                    ) -> Args:
        args = super()._subprocess(envs, log_level, init_fn, config)
        args.extend([
            "--outer-sandbox", "subprocess",
        ])
        return args

    def update_rules(self,
                     *,
                     envs: Envs,
                     config: ConfigLines) -> AllRules:
        return read_and_parse_config(envs=envs,
                                     config=config)

    def bash_args(self, envs: Envs) -> Args:
        return ["/bin/bash",
                "-c",
                "PS1='[os-sandbox-subprocess] $ '; "
                "export PS1; "
                "exec /bin/bash --norc --noprofile -i"], {}
