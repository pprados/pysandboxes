"""Unit tests for where the QEMU boot console log is opened."""

import os
import tempfile
from pathlib import Path

import pytest

from pysandboxes.python_sb import QEMU_CONSOLE_LOG_NAME, _open_qemu_console_log

# root ignores the permission bits these tests rely on.
skip_as_root = pytest.mark.skipif(os.geteuid() == 0, reason="requires a non-root user")


class TestOpenQemuConsoleLog:
    """The console log must never be the reason a run fails."""

    def test_writes_in_the_working_directory_when_possible(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        handle, path = _open_qemu_console_log()

        assert handle is not None
        handle.close()
        assert path == Path(QEMU_CONSOLE_LOG_NAME)
        assert (tmp_path / QEMU_CONSOLE_LOG_NAME).exists()

    @skip_as_root
    def test_falls_back_to_the_temp_dir_when_the_working_directory_is_read_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """podman remaps uids, so the project bind mount is not writable in the guest."""
        read_only = tmp_path / "ro"
        read_only.mkdir()
        fallback = tmp_path / "tmp"
        fallback.mkdir()
        monkeypatch.chdir(read_only)
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fallback))
        read_only.chmod(0o500)
        try:
            handle, path = _open_qemu_console_log()

            assert handle is not None
            handle.close()
            assert path == fallback / QEMU_CONSOLE_LOG_NAME.lstrip(".")
        finally:
            read_only.chmod(0o700)

    @skip_as_root
    def test_gives_up_quietly_when_nothing_is_writable(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No log is a degraded run, not a failed one."""
        read_only = tmp_path / "ro"
        read_only.mkdir()
        monkeypatch.chdir(read_only)
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(read_only))
        read_only.chmod(0o500)
        try:
            handle, path = _open_qemu_console_log()

            assert handle is None
            assert path is None
        finally:
            read_only.chmod(0o700)
