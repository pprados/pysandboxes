# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Regression: Docker-style ``/usr/local/bin/python*`` must stage ``/usr/local/lib`` for libpython."""

import sys
from pathlib import Path
from unittest.mock import patch

from pysandboxes.remote.qemu_sse_daemon import _execution_dirs_mounts


def test_execution_dirs_mounts_include_peer_usr_local_lib(tmp_path: Path) -> None:
    """``follow_links_executable`` no-ops for ``/usr/local/bin``; mounts must still see ``../lib``."""
    bindir = tmp_path / "usr" / "local" / "bin"
    libdir = tmp_path / "usr" / "local" / "lib"
    bindir.mkdir(parents=True)
    libdir.mkdir(parents=True)
    pyexe = bindir / "python3.13"
    pyexe.write_bytes(b"\x7fELF")
    (libdir / "libpython3.13.so.1.0").write_text("", encoding="utf-8")

    resolved_bin = bindir.resolve()
    resolved_lib = libdir.resolve()

    with (
        patch.object(sys, "executable", str(pyexe)),
        patch.object(sys, "path", []),
        patch(
            "pysandboxes.remote.qemu_sse_daemon.site.getsitepackages",
            return_value=[],
        ),
    ):
        specs = _execution_dirs_mounts()

    host_paths = {str(p.resolve()) for _, p, _ in specs}
    assert str(resolved_bin) in host_paths, "interpreter bin directory must be mounted"
    assert (
        str(resolved_lib) in host_paths
    ), "peer /usr/local/lib with libpython must be mounted"
