# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Cross-platform import behavior of the Windows Job Object helpers."""

import sys

import pytest

from pysandboxes.remote import win_job


def test_win_job_module_imports_without_loading_windows_dlls() -> None:
    assert callable(win_job.create_kill_on_close_job)


@pytest.mark.skipif(sys.platform == "win32", reason="requires a non-Windows host")
def test_win_job_api_fails_clearly_off_windows() -> None:
    with pytest.raises(OSError, match="available only on win32"):
        win_job.create_kill_on_close_job()
