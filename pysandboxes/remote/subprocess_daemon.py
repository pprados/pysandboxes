import asyncio
import logging
import os
import random
import sys
import time
from abc import abstractmethod
from pathlib import Path
from typing import Callable, List, Dict, Any, Tuple

from .base_daemon import BaseDaemon
from .tools import return_level_parameter, set_is_in_sandbox
from ..guard_sandbox import AllRules, read_and_parse_config

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


# async def read_parent_stdin_and_write_to_pty(fd_master: int) -> None:
#     """Lit les frappes clavier du parent et les écrit dans le PTY maître."""
#     while True:
#         try:
#             # Lecture bloquante mais dans un thread séparé
#             char_bytes: bytes = await asyncio.to_thread(
#                 sys.stdin.buffer.read, 1)
#             if not char_bytes:  # EOF (Ctrl+D)
#                 print("\nParent: EOF de stdin atteint.")
#                 break
#             # Écrire directement dans le descripteur de fichier maître
#             os.write(fd_master, char_bytes)
#         except OSError as e:
#             if e.errno == errno.EIO:  # Typical error when PTY master is closed
#                 print(
#                     "\nParent: Erreur EIO, PTY master probablement fermé.")
#                 break
#             print(
#                 f"\nParent: Erreur de lecture/écriture sur stdin parent: {e}")
#             break
#         except Exception as e:
#             print(
#                 f"\nParent: Erreur inattendue lors de la lecture stdin: {e}")
#             break
#

class BaseSubProcessDaemon(BaseDaemon):

    def __init__(self,
                 max_attempts: int = 1,  # Maximum number of retry _attempts TODO 5
                 base_delay: float = 0.1,  # Initial delay in seconds (e.g., 100 ms)
                 factor: float = 2.0,  # Exponential increase _factor
                 max_delay: float = 10.0,  # Maximum delay in seconds
                 reset_delay: float = 120.0  # delay to reset attemps
                 ):
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
        self._is_started=False

    def _subprocess(self,
                    envs: Dict[str, str],
                    log_level:int,
                    ) -> List[str]:
        from . import daemon
        cmd_parameters = [
            sys.executable,
            "-P",  # don't prepend a potentially unsafe path to sys.path; also PYTHONSAFEPATH

            "-u",  # FIXME unbuffered stdout and stderr
            "-m",
            daemon.__name__,
        ]
        verbose = return_level_parameter(log_level)
        if verbose:
            cmd_parameters.append(verbose)
        cmd_parameters.extend([
            "--outer-sandbox", "subprocess",
        ])
        return cmd_parameters

    @abstractmethod
    def update_rules(self, envs: Dict[str, str]) -> AllRules:
        pass

    @abstractmethod
    def bash_args(self, envs: Dict[str, str]) -> Tuple[str, Dict[str, Any]]:
        pass

    async def start(self, log_level:int,envs:dict[str,str]=None) -> Any:
        if not envs:
            envs=dict(os.environ)
        set_is_in_sandbox(True)
        self.restart = 0
        await self._re_start(envs, log_level, first=True)

    async def _re_start(self,
                        envs: Dict[str, str],
                        log_level:int,
                        first: bool = False) -> None:
        await self._re_start_cmd(self._subprocess(envs,log_level), {})
        if first:
            logger.info("daemon is started")
        else:
            logger.warning("daemon is re-started")

    async def _re_start_cmd(self,
                            args: List[str],
                            process_kwargs: Dict[str, Any],
                            stdin: bool = False,
                            stdout: bool = False) -> None:
        self._is_started=False
        umask = os.umask(0o002)
        umask = os.umask(umask) & 0o007  # Only keep user flags
        if DEBUG:
            Path("run.sh").write_text("#!/bin/bash\n" +  # FIXME:
                  args[0] + " " +
                  " \\\n  ".join(
                      param if " " not in param else repr(param) for param in args[1:]) +
                  "\n")
        self._process = await asyncio.create_subprocess_exec(
            *args,
            **process_kwargs,
            # FIXME: avec ceci, il n'y a plus de trace sur la console
            # Voir comment fixer cela.
            # stdout=asyncio.subprocess.PIPE,
            # stderr=asyncio.subprocess.PIPE,

            # close_fds=True,
            # cwd=None,
            # restore_signals=True,
            # #     # process_group=1,  # FIXME
            umask=umask,
            env=os.environ.copy(),
        )
        if stdin:
            self._stdin_task = asyncio.create_task(
                _write_stream(
                    self._process.stdin
                )
            )
        if stdout:
            self._stdout_task = asyncio.create_task(
                _read_stream(
                    self._process.stdout,
                    lambda line: print(line, file=sys.stdout, flush=True)
                )
            )
            self._stderr_task = asyncio.create_task(
                _read_stream(
                    self._process.stderr,
                    lambda line: print(line, file=sys.stderr, flush=True)
                )
            )
        # FIXME self.task = asyncio.create_task(self.daemon.serve())
        self._is_started=True


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
        self._is_started=False
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

    # def convert_rules(self, rules: AllRules) -> AllRules:
    #     return rules


class SubProcessDaemon(BaseSubProcessDaemon):
    def update_rules(self, envs: Dict[str, str]):
        return read_and_parse_config(envs=envs)

    def bash_args(self, envs: Dict[str, str]) -> Tuple[str, Dict[str, Any]]:
        return ["/bin/bash",
                "-c",
                "PS1='[os-sandbox-subprocess] $ '; "
                "export PS1; "
                "exec /bin/bash --norc --noprofile -i"], {}
