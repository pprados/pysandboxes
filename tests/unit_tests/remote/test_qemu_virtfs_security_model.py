# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A host symlink read through 9p mapped-xattr fails with ELOOP in the guest.

``/etc/ssl/certs`` is made of such links, so HTTPS under qemu failed with "certificate
verify failed" until the CA stores were shared with ``security_model=none``.
"""

from pathlib import Path

import pytest

from pysandboxes.remote import qemu_sse_daemon
from pysandboxes.remote.qemu_sse_daemon import _virtfs_security_model


def test_a_ca_store_is_shared_without_mapped_xattr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = tmp_path / "ssl"
    store.mkdir()
    monkeypatch.setattr(qemu_sse_daemon, "_CA_STORES", (str(store) + "/",))

    assert _virtfs_security_model(store, "mapped-xattr") == "none"


def test_other_mounts_keep_the_configured_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qemu_sse_daemon, "_CA_STORES", (str(tmp_path / "ssl") + "/",))

    assert _virtfs_security_model(tmp_path, "mapped-xattr") == "mapped-xattr"
    assert _virtfs_security_model(tmp_path, "auto") == "mapped-xattr"
    assert _virtfs_security_model(tmp_path, "passthrough") == "passthrough"


def test_a_staged_tree_is_shared_without_mapped_xattr(tmp_path: Path) -> None:
    staged = tmp_path / "virtfs_stage_exec"
    staged.mkdir()

    assert _virtfs_security_model(staged, "mapped-xattr") == "none"
