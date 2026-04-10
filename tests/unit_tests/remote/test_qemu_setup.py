# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests for QEMU guest bootstrap helpers."""

from pathlib import Path

from pysandboxes.all_rules import AllRules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote.qemu_setup import (
    PYSANDBOXES_GUEST_DIAG,
    PYSANDBOXES_GUEST_DIAG_FROM_PROFILE,
    merge_qemu_guest_diag_env,
)
from pysandboxes.sb_types import Envs


def _minimal_rules(
    *,
    os_sandbox_params: dict[str, str] | None = None,
    envs: dict[str, str] | None = None,
) -> AllRules:
    return AllRules(
        root_path=Path("."),
        config=[],
        envs=Envs(envs or {}),
        os_sandbox="qemu",
        os_sandbox_params=ImmutableDict(os_sandbox_params or {}),
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


def test_merge_qemu_guest_diag_env_off_by_default() -> None:
    rules = _minimal_rules()
    out = merge_qemu_guest_diag_env(rules)
    assert out is rules
    assert PYSANDBOXES_GUEST_DIAG not in dict(out.envs)


def test_merge_qemu_guest_diag_env_injects_when_true() -> None:
    rules = _minimal_rules(
        os_sandbox_params={"guest_diag": "true"}, envs={"FOO": "bar"}
    )
    out = merge_qemu_guest_diag_env(rules)
    assert dict(out.envs)[PYSANDBOXES_GUEST_DIAG] == PYSANDBOXES_GUEST_DIAG_FROM_PROFILE
    assert dict(out.envs)["FOO"] == "bar"
