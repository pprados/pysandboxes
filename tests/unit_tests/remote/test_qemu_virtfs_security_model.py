# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A host symlink read through 9p mapped-xattr fails with ELOOP in the guest.

``/etc/ssl/certs`` is made of such links, so HTTPS under qemu failed with "certificate
verify failed" until the CA stores were shared with ``security_model=none``.
"""

from pathlib import Path

import pytest

from pysandboxes.remote import qemu_sse_daemon
from pysandboxes.remote.qemu_sse_daemon import _qemu_escape_value, _virtfs_security_model


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


def test_an_unknown_configured_model_falls_back_instead_of_reaching_the_command_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A free-form string here used to be forwarded as-is into ``-virtfs security_model=...``,

    so a value containing a comma (e.g. ``mapped-xattr,readonly=off``) could append an
    unintended QEMU sub-option. Only QEMU's own security models are accepted.
    """
    with caplog.at_level("WARNING"):
        assert _virtfs_security_model(tmp_path, "mapped-xattr,readonly=off") == "mapped-xattr"

    assert "Invalid qemu.virtfs_security_model" in caplog.text


def test_a_comma_in_a_value_is_doubled_as_qemus_own_escape() -> None:
    """QEMU reads an un-escaped comma as the start of another sub-option on the same line."""
    assert _qemu_escape_value("/mnt/a,b") == "/mnt/a,,b"
    assert _qemu_escape_value("/plain/path") == "/plain/path"
