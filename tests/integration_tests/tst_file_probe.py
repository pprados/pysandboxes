# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Half of test_os_file_confinement: what a confined process may do to files, the Python guards being off.

Run as ``python -m tests.integration_tests.tst_file_probe [--plain] <profile> <ro_file> <ro_dir> <outside_file>
<rw_dir> <host_tmp_file>``. With ``--plain`` the checks run in this very process, which `python-sb` has already
confined; without it they run in a ``@sandbox`` function, so the daemon of the provider does the confining.
"""

import ctypes
import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import cast

from pysandboxes import sandbox, sandboxes


def _outcome(action: Callable[[], object]) -> str:
    try:
        action()
    except OSError as e:
        return f"DENIED {type(e).__name__}"
    return "ALLOWED"


def _make_temporary_file() -> None:
    descriptor, name = tempfile.mkstemp()
    os.close(descriptor)
    os.unlink(name)


def _native_read(path: str) -> bytes:
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.open(path.encode(), os.O_RDONLY)
    if fd < 0:
        raise OSError(ctypes.get_errno(), path)
    try:
        chunks: list[bytes] = []
        buffer = ctypes.create_string_buffer(65536)
        while True:
            size = libc.read(fd, buffer, len(buffer))
            if size < 0:
                raise OSError(ctypes.get_errno(), path)
            if not size:
                return b"".join(chunks)
            chunks.append(buffer.raw[:size])
    finally:
        libc.close(fd)


def _native_open_write(path: str) -> None:
    """Prove write-open permission without changing the host sentinel."""
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.open(path.encode(), os.O_WRONLY)
    if fd < 0:
        raise OSError(ctypes.get_errno(), path)
    libc.close(fd)


def _native_write(path: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.open(path.encode(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    if fd < 0:
        raise OSError(ctypes.get_errno(), path)
    try:
        assert libc.write(fd, b"written", 7) == 7
    finally:
        libc.close(fd)


def _check_files(
    ro_file: str,
    ro_dir: str,
    outside_file: str,
    rw_dir: str,
    host_tmp_file: str,
    native: bool = False,
    ignored_digest: str = "",
) -> str:
    def read(path: str) -> object:
        return _native_read(path) if native else Path(path).read_text()

    def write(path: str) -> object:
        if native:
            _native_write(path)
            return None
        return Path(path).write_text("written")

    outcomes = {
        "ro_read": _outcome(lambda: read(ro_file)),
        "ro_write": _outcome(
            lambda: _native_open_write(ro_file) if native else write(str(Path(ro_dir) / "created.txt"))
        ),
        "outside_read": _outcome(lambda: read(outside_file)),
        "rw_write": _outcome(lambda: write(str(Path(rw_dir) / "created.txt"))),
        "host_tmp_read": _outcome(lambda: read(host_tmp_file)),
        "own_tmp_write": _outcome(_make_temporary_file),
    }
    if native:
        try:
            digest = hashlib.sha256(_native_read(str(Path(ro_dir) / "README.md"))).hexdigest()
            outcomes["ignored_read"] = "DENIED" if digest != ignored_digest else "ALLOWED"
        except OSError:
            outcomes["ignored_read"] = "DENIED"
        outcomes["env_secret"] = "ALLOWED" if "MICROVM_HOST_SECRET" in os.environ else "DENIED"
    return json.dumps(outcomes)


@sandbox
def _check_files_in_sandbox(
    ro_file: str,
    ro_dir: str,
    outside_file: str,
    rw_dir: str,
    host_tmp_file: str,
    native: bool = False,
    ignored_digest: str = "",
) -> str:
    return _check_files(ro_file, ro_dir, outside_file, rw_dir, host_tmp_file, native, ignored_digest)


def main() -> int:
    args = [arg for arg in sys.argv[1:] if arg not in ("--plain", "--native")]
    profile, paths = args[0], cast(tuple[str, str, str, str, str], tuple(args[1:6]))
    ignored_digest = args[6] if "--native" in sys.argv else ""
    if "--plain" in sys.argv:
        print(_check_files(*paths, native="--native" in sys.argv, ignored_digest=ignored_digest))
        return 0
    with sandboxes(sandboxes_config=profile):
        print(_check_files_in_sandbox(*paths, native="--native" in sys.argv, ignored_digest=ignored_digest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
