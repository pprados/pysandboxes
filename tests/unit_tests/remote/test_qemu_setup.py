# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests for QEMU guest bootstrap helpers."""

from pathlib import Path

from pysandboxes.all_rules import AllRules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote.qemu_setup import (
    _bootstrap_script_content,
    _qemu_show_boot_console_truthy,
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


def test_qemu_show_boot_console_truthy_from_profile() -> None:
    rules = _minimal_rules(os_sandbox_params={"show_boot_console": "true"})
    assert _qemu_show_boot_console_truthy(rules) is True


def test_qemu_show_boot_console_truthy_false_when_unset() -> None:
    assert _qemu_show_boot_console_truthy(_minimal_rules()) is False


def test_qemu_show_boot_console_truthy_false_explicit() -> None:
    rules = _minimal_rules(os_sandbox_params={"show_boot_console": "false"})
    assert _qemu_show_boot_console_truthy(rules) is False


def test_qemu_bootstrap_exports_color_env_for_serial_console() -> None:
    script = _bootstrap_script_content(
        [],
        "/mnt/pysandbox_run",
        "3.12",
        bootstrap_verbose=False,
    )
    assert "export TERM=xterm-256color" in script
    assert "export FORCE_COLOR=1" in script
    assert "PY_COLORS" not in script
