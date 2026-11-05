# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The rows of the integration suites: the emulated QEMU row exists only when it is asked for."""

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
    assert [r for r in _env.os_sandbox_rows(tcg=True) if r != "qemu-tcg"] == list(_env.os_sandbox_rows(tcg=False))


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
