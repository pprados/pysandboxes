# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The Win32 window-object helper must remain importable off Windows."""

import sys

import pytest

from pysandboxes.remote import win_window
from pysandboxes.remote import appcontainer_launcher


def test_window_helpers_import_without_loading_windows_dlls() -> None:
    assert callable(win_window.grant_service_window_access)
    assert callable(win_window.remove_service_window_access)
    assert callable(appcontainer_launcher.run)


@pytest.mark.skipif(sys.platform == "win32", reason="This check is for non-Windows hosts")
def test_window_helpers_fail_clearly_off_windows() -> None:
    with pytest.raises(OSError, match="only on win32"):
        win_window.grant_service_window_access("S-1-15-2-1")
    with pytest.raises(OSError, match="only on win32"):
        win_window.remove_service_window_access("S-1-15-2-1")
