# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The QEMU port forward must listen on the host loopback only.

``hostfwd=tcp::PORT`` binds every host interface: any machine on the LAN could
reach the daemon's ``/ping`` and SSE endpoints. The host always connects through
``127.0.0.1``, so the forward is pinned to that address.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from pysandboxes.all_rules import AllRules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote.qemu_sse_daemon import QemuSSEDaemon
from pysandboxes.sb_types import Envs


def _rules() -> AllRules:
    return AllRules(
        root_path=Path("."),
        config=[],
        envs=Envs({}),
        os_sandbox="qemu",
        os_sandbox_params=ImmutableDict({}),
        use_py_sandbox=True,
        port=-1,
        learning_path=Path(),
        learn=False,
        envs_rules=(),
        socket_rules=(),
        pin_dns=ImmutableDict({}),
        file_rules=(),
        import_rules=(),
    )


def test_hostfwd_binds_the_host_loopback(tmp_path: Path) -> None:
    module = "pysandboxes.remote.qemu_sse_daemon"
    with (
        patch(f"{module}.get_default_image_path", return_value=tmp_path / "image.qcow2"),
        patch(f"{module}.ensure_image"),
        patch(f"{module}._file_rules_mounts", return_value=([], [])),
        patch(f"{module}.prepare_guest_env", return_value=tmp_path / "nocloud.iso"),
        patch(f"{module}.qemu_accel_args", return_value=[]),
        patch(f"{module}._qemu_binary", return_value="qemu-system-x86_64"),
    ):
        cmd, _ = QemuSSEDaemon("token")._build_qemu_cmd(_rules(), tmp_path, MagicMock(), 4242, tmp_path / "pipe")

    nic = cmd[cmd.index("-nic") + 1]
    assert "hostfwd=tcp:127.0.0.1:4242-:4242" in nic
