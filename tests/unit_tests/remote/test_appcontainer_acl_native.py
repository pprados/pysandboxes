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


_PACKAGE = "S-1-15-2-1"
_RUNTIME = "S-1-15-3-4096"
_OTHER = "S-1-5-32-545"


def test_a_mask_denies_the_package_and_drops_its_grants_but_keeps_the_others(tmp_path: Path) -> None:
    target = tmp_path / "secret.txt"
    target.touch()
    appcontainer_acl._grant_dacl(target, _PACKAGE, appcontainer_acl._READ_EXECUTE, False)
    appcontainer_acl._grant_dacl(target, _OTHER, appcontainer_acl._READ_EXECUTE, False)

    appcontainer_acl._deny_access(target, _PACKAGE, _RUNTIME, protect_inheritance=True)

    sddl = appcontainer_acl._dacl_sddl(target)
    assert sddl.startswith("D:P")
    assert "(D;;FA;;;AC)(" in sddl
    assert "(A;;0x1200a9;;;AC)" not in sddl
    assert "(A;;0x1200a9;;;BU)" in sddl


def test_a_mask_makes_the_inherited_entries_explicit_and_can_be_restored(tmp_path: Path) -> None:
    target = tmp_path / "secret.txt"
    target.touch()
    original = appcontainer_acl._dacl_sddl(target)
    assert "D:P" not in original

    appcontainer_acl._deny_access(target, _PACKAGE, _RUNTIME, protect_inheritance=True)
    masked = appcontainer_acl._dacl_sddl(target)
    assert masked.startswith("D:P") and "(D;;FA;;;AC)(" in masked and ";ID;" not in masked

    appcontainer_acl._set_acl_sddl(target, original)
    restored = appcontainer_acl._dacl_sddl(target)
    assert restored[restored.index("(") :] == original[original.index("(") :]
    assert "D:P" not in restored


def test_a_second_mask_keeps_the_protection_and_denies_the_second_package(tmp_path: Path) -> None:
    target = tmp_path / "secret.txt"
    target.touch()
    appcontainer_acl._deny_access(target, _PACKAGE, _RUNTIME, protect_inheritance=True)

    appcontainer_acl._deny_access(target, _OTHER, _RUNTIME, protect_inheritance=False)

    sddl = appcontainer_acl._dacl_sddl(target)
    assert sddl.startswith("D:P") and "(D;;FA;;;BU)(D;;FA;;;AC)" in sddl
