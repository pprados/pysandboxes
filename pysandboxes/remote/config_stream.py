# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Read the config pickle from the head of a stream, and leave the rest of the stream to the program."""

import os
import pickle
from typing import Any


class _ExactReader:
    """A reader of a file descriptor that never returns a short read, so a pickle never consumes more than its own."""

    def __init__(self, fd: int) -> None:
        self._fd = fd

    def read(self, size: int = -1) -> bytes:
        out = bytearray()
        while size < 0 or len(out) < size:
            chunk = os.read(self._fd, 1 << 16 if size < 0 else size - len(out))
            if not chunk:
                break
            out += chunk
        return bytes(out)

    def readinto(self, buffer: Any) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def readline(self) -> bytes:
        out = bytearray()
        while not out.endswith(b"\n"):
            byte = os.read(self._fd, 1)
            if not byte:
                break
            out += byte
        return bytes(out)


def load_config_from_fd(fd: int) -> Any:
    """Unpickle the config written first on ``fd``; what follows it stays unread, for the program run in the sandbox."""
    return pickle.load(_ExactReader(fd))  # noqa: S301 - written by the trusted parent
