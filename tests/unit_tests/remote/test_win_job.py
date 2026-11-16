# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Cross-platform import behavior of the Windows Job Object helpers."""

import sys

import pytest

from pysandboxes.remote import win_job


def test_win_job_module_imports_without_loading_windows_dlls() -> None:
    assert callable(win_job.create_kill_on_close_job)


def test_the_ui_restrictions_cover_every_uilimit_flag_including_display_settings() -> None:
    """``_UI_LIMIT_FLAGS`` must lock down the full UI surface a Job Object can restrict.

    Regression: JOB_OBJECT_UILIMIT_DISPLAYSETTINGS (0x10) was missing, leaving a sandboxed
    process free to change the host's display settings despite every other UI right denied.
    """
    every_uilimit_flag = 0x01 | 0x02 | 0x04 | 0x08 | 0x10 | 0x20 | 0x40 | 0x80

    assert win_job._UI_LIMIT_FLAGS == every_uilimit_flag


@pytest.mark.skipif(sys.platform == "win32", reason="requires a non-Windows host")
def test_win_job_api_fails_clearly_off_windows() -> None:
    with pytest.raises(OSError, match="available only on win32"):
        win_job.create_kill_on_close_job()
