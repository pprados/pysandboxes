import asyncio
import logging
import os
import random
import sys
from typing import Callable

from .abstract_start_daemon import BaseStartDaemon

logger = logging.getLogger(__name__)


async def _read_stream(
        stream: asyncio.StreamReader,
        callback: Callable[[str], None]) -> None:
    while True:
        line: bytes = await stream.readline()
        if line:
            callback(line.decode('utf-8').strip())
        else:
            break


class ProcessDaemon(BaseStartDaemon):

    def __init__(self,
                 max_attempts: int = 5,  # Maximum number of retry _attempts
                 base_delay: float = 0.1,  # Initial delay in seconds (e.g., 100 ms)
                 factor: float = 2.0,  # Exponential increase _factor
                 max_delay: float = 10.0,  # Maximum delay in seconds
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

    async def _re_start(self) -> None:
        from . import daemon
        umask = os.umask(0o002)
        umask = os.umask(umask) & 0o007  # Only keep user flags
        self._process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            daemon.__name__,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,

            close_fds=True,
            cwd=None,
            restore_signals=True,
            start_new_session=False,
            # #     # process_group=1,  # FIXME
            umask=umask,
            env=os.environ.copy(),
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
