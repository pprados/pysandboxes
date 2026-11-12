# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""``PYSANDBOXES_RPC_TIMEOUT`` sets how long a call into the sandbox may take before the host gives up.

The first call of a program that imports a heavy library runs the import inside the guest, which a slow runner
needs far longer than 120 seconds for.
"""

import pytest

from pysandboxes.remote.parameters import TIMEOUT_FOR_RPC_CALL, rpc_call_timeout


@pytest.fixture(autouse=True)
def no_environment_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYSANDBOXES_RPC_TIMEOUT", raising=False)


def test_without_the_variable_the_default_applies() -> None:
    assert rpc_call_timeout() == float(TIMEOUT_FOR_RPC_CALL)


def test_a_given_default_applies_without_the_variable() -> None:
    assert rpc_call_timeout(20) == 20.0


def test_the_variable_sets_the_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYSANDBOXES_RPC_TIMEOUT", "900")
    assert rpc_call_timeout() == 900.0


def test_the_variable_wins_over_a_given_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYSANDBOXES_RPC_TIMEOUT", "300")
    assert rpc_call_timeout(20) == 300.0


def test_spaces_around_the_value_do_not_matter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYSANDBOXES_RPC_TIMEOUT", " 450.5 ")
    assert rpc_call_timeout() == 450.5


@pytest.mark.parametrize("value", ["", "soon", "0", "-30", "nan", "inf"])
def test_a_value_that_is_not_a_positive_duration_is_ignored(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Waiting forever, or not at all, would be worse than ignoring the variable."""
    monkeypatch.setenv("PYSANDBOXES_RPC_TIMEOUT", value)
    assert rpc_call_timeout() == float(TIMEOUT_FOR_RPC_CALL)
