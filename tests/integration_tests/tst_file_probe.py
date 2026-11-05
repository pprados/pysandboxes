# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Half of test_os_file_confinement: what a confined process may do to files, the Python guards being off.

Run as ``python -m tests.integration_tests.tst_file_probe [--plain] <profile> <ro_file> <ro_dir> <outside_file>
<rw_dir> <host_tmp_file>``. With ``--plain`` the checks run in this very process, which `python-sb` has already
confined; without it they run in a ``@sandbox`` function, so the daemon of the provider does the confining.
"""

import ctypes
import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

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


def _native_read(path: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.open(path.encode(), os.O_RDONLY)
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


def _check_files(ro_file: str, ro_dir: str, outside_file: str, rw_dir: str, host_tmp_file: str) -> str:
    return json.dumps(
        {
            "ignored_read": _outcome(lambda: _native_read(str(Path(ro_dir) / ".env"))),
            "env_secret": "ALLOWED" if "MICROVM_HOST_SECRET" in os.environ else "DENIED",
            "ro_read": _outcome(lambda: _native_read(ro_file)),
            "ro_write": _outcome(lambda: _native_write(str(Path(ro_dir) / "created.txt"))),
            "outside_read": _outcome(lambda: _native_read(outside_file)),
            "rw_write": _outcome(lambda: _native_write(str(Path(rw_dir) / "created.txt"))),
            "host_tmp_read": _outcome(lambda: _native_read(host_tmp_file)),
            "own_tmp_write": _outcome(_make_temporary_file),
        }
    )


@sandbox
def _check_files_in_sandbox(ro_file: str, ro_dir: str, outside_file: str, rw_dir: str, host_tmp_file: str) -> str:
    return _check_files(ro_file, ro_dir, outside_file, rw_dir, host_tmp_file)


def main() -> int:
    args = [arg for arg in sys.argv[1:] if arg != "--plain"]
    profile, paths = args[0], args[1:6]
    if "--plain" in sys.argv:
        print(_check_files(*paths))
        return 0
    with sandboxes(sandboxes_config=profile):
        print(_check_files_in_sandbox(*paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
