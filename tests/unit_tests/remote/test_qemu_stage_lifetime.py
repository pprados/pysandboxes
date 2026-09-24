# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The staged 9p trees must live as long as the VM, not as long as its start.

``_re_start`` builds the QEMU command inside a ``TemporaryDirectory`` that is
removed as soon as the guest answers its first ping. Staging the execution trees
there deleted the files the running guest serves over 9p: every import the guest
made later failed with ``No module named ...``.
"""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pysandboxes.all_rules import AllRules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote.qemu_sse_daemon import QemuSSEDaemon
from pysandboxes.sb_types import Envs


class _StopLaunch(RuntimeError):
    """Stops the start right after the command is built."""


def _rules() -> AllRules:
    return AllRules(
        root_path=Path("."),
        config=[],
        envs=Envs({}),
        os_sandbox="qemu",
        os_sandbox_params=ImmutableDict({"virtfs": "on"}),
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


def _fake_build(staged: list[Path]) -> Any:
    def fake_build(self: QemuSSEDaemon, all_rules: AllRules, temp: Path, *args: Any, **kwargs: Any) -> None:
        marker = (kwargs.get("stage_root") or temp) / "virtfs_stage_exec" / "module.py"
        marker.parent.mkdir(parents=True)
        marker.write_text("")
        marker.parent.chmod(0o555)  # staging keeps the modes of read-only trees
        staged.append(marker)
        raise _StopLaunch

    return fake_build


async def test_the_staged_trees_outlive_the_start_and_go_with_the_vm() -> None:
    staged: list[Path] = []
    daemon = QemuSSEDaemon("token")
    with patch.object(QemuSSEDaemon, "_build_qemu_cmd", _fake_build(staged)):
        with pytest.raises(_StopLaunch):
            await daemon._re_start(_rules(), envs={}, log_level=logging.INFO, init_fn=None)

    assert staged[0].exists()
    await daemon._shutdown(graceful_shutdown=False)
    assert not staged[0].exists()


async def test_a_failed_start_leaves_no_staged_tree_behind() -> None:
    staged: list[Path] = []
    daemon = QemuSSEDaemon("token")
    with patch.object(QemuSSEDaemon, "_build_qemu_cmd", _fake_build(staged)):
        with pytest.raises(_StopLaunch):
            await daemon._start(_rules(), envs={}, log_level=logging.INFO, init_fn=None)

    assert not staged[0].exists()
