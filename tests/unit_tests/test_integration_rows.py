# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The rows of the integration suites: the emulated QEMU row exists only when it is asked for."""

import sys

import pytest

from tests.integration_tests import _env


def test_the_emulated_qemu_row_is_left_out_by_default() -> None:
    assert "qemu-tcg" not in _env.os_sandbox_rows(tcg=False)


def test_the_accelerated_qemu_row_stays_when_the_emulated_one_is_left_out() -> None:
    assert "qemu" in _env.os_sandbox_rows(tcg=False)


def test_the_emulated_qemu_row_follows_the_accelerated_one_when_asked_for() -> None:
    rows = _env.os_sandbox_rows(tcg=True)

    assert rows.index("qemu-tcg") == rows.index("qemu") + 1


def test_asking_for_the_emulated_row_only_adds_that_row() -> None:
    assert [r for r in _env.os_sandbox_rows(tcg=True) if not r.endswith("-tcg")] == list(
        _env.os_sandbox_rows(tcg=False)
    )


@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE"])
def test_the_environment_variable_asks_for_the_emulated_row(value: str) -> None:
    assert _env.qemu_tcg_requested({"PYSANDBOXES_QEMU_TCG": value}) is True


@pytest.mark.parametrize(
    "environ", [{}, {"PYSANDBOXES_QEMU_TCG": ""}, {"PYSANDBOXES_QEMU_TCG": "0"}, {"PYSANDBOXES_QEMU_TCG": "no"}]
)
def test_the_emulated_row_is_not_asked_for_otherwise(environ: dict[str, str]) -> None:
    assert _env.qemu_tcg_requested(environ) is False


def test_microvm_is_an_accelerated_integration_row() -> None:
    assert "qemu-microvm" in _env.os_sandbox_rows(tcg=False)
    assert _env.backend_of("qemu-microvm") == "qemu-microvm"
    assert _env.row_profile_lines("qemu-microvm") == "qemu.use_kvm=true\n"


def test_microvm_tcg_row_refuses_acceleration() -> None:
    rows = _env.os_sandbox_rows(tcg=True)
    assert rows.index("qemu-microvm-tcg") == rows.index("qemu-microvm") + 1
    assert _env.backend_of("qemu-microvm-tcg") == "qemu-microvm"
    assert _env.row_profile_lines("qemu-microvm-tcg") == "qemu.use_kvm=false\n"


def test_accelerated_microvm_row_refuses_missing_kvm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_env, "provider_unavailable_reason", lambda _: None)
    monkeypatch.setattr(_env, "is_kvm_available", lambda: False)
    assert "KVM" in (_env.provider_skip_reason("qemu-microvm") or "")
    assert _env.provider_skip_reason("qemu-microvm-tcg") is None


@pytest.mark.skipif(sys.platform != "linux", reason="process identity uses Linux /proc")
def test_owned_qemu_identity_includes_zombies_and_rejects_pid_reuse() -> None:
    import os
    import time
    from pathlib import Path
    from tests.integration_tests.test_temp_cleanup import _owned_process_exists

    pid = os.fork()
    if pid == 0:
        os._exit(0)
    try:
        path = Path(f"/proc/{pid}/stat")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            stat = path.read_text().rsplit(")", 1)[1].split()
            if stat[0] == "Z":
                break
            time.sleep(0.01)
        assert stat[0] == "Z"
        assert _owned_process_exists(pid, stat[19])
        assert not _owned_process_exists(pid, str(int(stat[19]) + 1))
    finally:
        os.waitpid(pid, 0)
    assert not _owned_process_exists(pid, stat[19])
