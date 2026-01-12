import asyncio
import errno
import logging
import os
import random
import sys
from abc import abstractmethod
from typing import Callable, List, Dict, Any, Tuple

from .abstract_start_daemon import BaseStartDaemon
from .. import guard_files
from ..guard_sandbox import AllRules

logger = logging.getLogger(__name__)


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
                if not line:  # EOF (End Of File) atteint
                    print("Parent: EOF de stdin atteint.")
                    break
                print(f"Parent lit de son stdin: {line.strip()}")
                child_stdin_writer.write(line.encode('utf-8'))
                await child_stdin_writer.drain()
            except Exception as e:
                print(f"Erreur lors de la lecture/écriture: {e}")
                break
    finally:
        # Assurez-vous de restaurer les paramètres du terminal parent à la fin
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
        # Fermer le descripteur maître si toujours ouvert
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


async def read_parent_stdin_and_write_to_pty(fd_master: int) -> None:
    """Lit les frappes clavier du parent et les écrit dans le PTY maître."""
    while True:
        try:
            # Lecture bloquante mais dans un thread séparé
            char_bytes: bytes = await asyncio.to_thread(
                sys.stdin.buffer.read, 1)
            if not char_bytes:  # EOF (Ctrl+D)
                print("\nParent: EOF de stdin atteint.")
                break
            # Écrire directement dans le descripteur de fichier maître
            os.write(fd_master, char_bytes)
        except OSError as e:
            if e.errno == errno.EIO:  # Typical error when PTY master is closed
                print(
                    "\nParent: Erreur EIO, PTY master probablement fermé.")
                break
            print(
                f"\nParent: Erreur de lecture/écriture sur stdin parent: {e}")
            break
        except Exception as e:
            print(
                f"\nParent: Erreur inattendue lors de la lecture stdin: {e}")
            break


class BaseSubProcessDaemon(BaseStartDaemon):

    def __init__(self,
                 max_attempts: int = 1,  # Maximum number of retry _attempts TODO 5
                 base_delay: float = 0.1,  # Initial delay in seconds (e.g., 100 ms)
                 factor: float = 2.0,  # Exponential increase _factor
                 max_delay: float = 10.0,  # Maximum delay in seconds
                 # TODO: delay to reset attemps
                 ):
        self._process = None
        self._stdout_task = None
        self._stderr_task = None
        self._attempts = 0
        self._base_delay = base_delay
        self._factor = factor
        self._max_delay = max_delay
        self._max_attempts = max_attempts

    async def _start(self) -> None:
        self.restart = 0
        await self._re_start()

    def _subprocess(self) -> List[str]:
        from . import daemon
        return [
            sys.executable,
            "-m",
            daemon.__name__
        ]

    @abstractmethod
    def bash_args(self,envs:Dict[str,str]) -> Tuple[str, Dict[str,Any]]:
        pass

    async def _re_start(self) -> None:
        await self._re_start_cmd(self._subprocess(), {})

    async def _re_start_cmd(self,
                            args: List[str],
                            kwargs: Dict[str, Any],
                            stdin: bool = False) -> None:
        umask = os.umask(0o002)
        umask = os.umask(umask) & 0o007  # Only keep user flags
        self._process = await asyncio.create_subprocess_exec(
            *args,
            **kwargs,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,

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
        logger.warning("Sandbox Daemon in subprocess is started")
        # self.task = asyncio.create_task(self.daemon.serve())

    async def close(self) -> None:
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
        logger.info("daemon is shutdown")

    async def join(self) -> int:
        errorlevel = -1
        while errorlevel != 0:
            errorlevel = await self._process.wait()
            if errorlevel != 0:
                self._attempts += 1
                if self._attempts > self._max_attempts:
                    return errorlevel
                # Calculate the base delay for this attempt
                current_base_backoff: float = min(self._max_delay, self._base_delay * (
                        self._factor ** (self._attempts - 1)))

                wait_time: float = random.uniform(current_base_backoff * 0.9,
                                                  current_base_backoff)
                await asyncio.sleep(wait_time)
                logger.warning("process restarting")
                await self.close()
                await self._re_start()
        return errorlevel

    def convert_rules(self, rules: AllRules) -> AllRules:
        args = []
        sandbox_env, provider, socket_rules, files_rules = guard_files.parse_rules(
            rules)

        # 1. env
        pass  # Nothing

        # 2. provider


class SubProcessDaemon(BaseSubProcessDaemon):
    def bash_args(self,envs:Dict[str,str]) -> Tuple[str, Dict[str,Any]]:
        return ["/bin/bash",
                "-c",
                "PS1='[os-sandbox-subprocess] $ '; "
                "export PS1; "
                "exec /bin/bash --norc --noprofile -i"],{}
