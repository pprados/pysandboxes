# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests for QEMU guest bootstrap helpers."""

import subprocess
from pathlib import Path

from pysandboxes.all_rules import AllRules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.remote.qemu_guest_console_io import GUEST_STDERR_FILE
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


def _shell_function(script: str, name: str) -> str:
    lines = script.splitlines()
    start = lines.index(f"{name}() {{")
    return "\n".join(lines[start : lines.index("}", start) + 1])


def test_a_fatal_bootstrap_error_reaches_the_run_dir_stderr(tmp_path: Path) -> None:
    # The console is hidden by default: a guest whose interpreter cannot start (a host
    # Python built against a newer glibc than the image's) used to fail with rc=1 and
    # nothing on the host side.
    script = _bootstrap_script_content([], str(tmp_path), "3.12")
    snippet = "\n".join(
        [
            _shell_function(script, "_pysb_fatal"),
            "_pysb_halt_guest() { :; }",
            '_pysb_fatal "probe failed: version GLIBC_2.38 not found"',
        ]
    )
    result = subprocess.run(["bash", "-c", snippet], capture_output=True, text=True)
    assert result.returncode == 1
    assert "GLIBC_2.38" in result.stderr
    assert "GLIBC_2.38" in (tmp_path / GUEST_STDERR_FILE).read_text()


def test_the_python_probe_failure_is_fatal_with_its_stderr() -> None:
    script = _bootstrap_script_content([], "/mnt/pysandbox_run", "3.12")
    assert '_pysb_fatal "Python probe rc=$PY_PROBE_RC from $PYTHON_EXE: $(cat "$PROBE_ERR")"' in script
