# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The DACL helpers of the AppContainer provider, against the real Windows security API."""

import subprocess
import sys
from pathlib import Path

import pytest

from pysandboxes.remote import appcontainer_acl

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows ACLs")

_ALL_APPLICATION_PACKAGES = "S-1-15-2-1"


def _listing(path: Path) -> str:
    return subprocess.run(["icacls.exe", str(path)], capture_output=True, text=True, check=True).stdout


def test_a_grant_is_read_back_and_inherited_by_the_children(tmp_path: Path) -> None:
    child = tmp_path / "child.txt"
    child.touch()
    assert not appcontainer_acl._has_allow_ace(tmp_path, (_ALL_APPLICATION_PACKAGES,), appcontainer_acl._READ_EXECUTE)

    appcontainer_acl._grant_dacl(tmp_path, _ALL_APPLICATION_PACKAGES, appcontainer_acl._READ_EXECUTE, True)

    assert appcontainer_acl._has_allow_ace(tmp_path, (_ALL_APPLICATION_PACKAGES,), appcontainer_acl._READ_EXECUTE)
    assert "ALL APPLICATION PACKAGES" in _listing(child)


def test_a_read_grant_does_not_cover_write(tmp_path: Path) -> None:
    appcontainer_acl._grant_dacl(tmp_path, _ALL_APPLICATION_PACKAGES, appcontainer_acl._READ_EXECUTE, True)

    assert not appcontainer_acl._has_allow_ace(tmp_path, (_ALL_APPLICATION_PACKAGES,), appcontainer_acl._MODIFY)


def test_a_revoke_removes_the_grant_from_the_path_and_its_children(tmp_path: Path) -> None:
    child = tmp_path / "child.txt"
    child.touch()
    appcontainer_acl._grant_dacl(tmp_path, _ALL_APPLICATION_PACKAGES, appcontainer_acl._READ_EXECUTE, True)

    appcontainer_acl._revoke_dacl(tmp_path, _ALL_APPLICATION_PACKAGES)

    assert not appcontainer_acl._has_allow_ace(tmp_path, (_ALL_APPLICATION_PACKAGES,), appcontainer_acl._READ_EXECUTE)
    assert "ALL APPLICATION PACKAGES" not in _listing(child)


def test_a_missing_path_is_reported_as_an_os_error(tmp_path: Path) -> None:
    with pytest.raises(OSError):
        appcontainer_acl._grant_dacl(tmp_path / "missing", _ALL_APPLICATION_PACKAGES, appcontainer_acl._MODIFY, False)
