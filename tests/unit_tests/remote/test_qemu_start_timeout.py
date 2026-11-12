# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""``qemu.start_timeout`` sets how long the VM has to answer, and nothing else caps it.

Two independent limits used to bound a QEMU daemon start: a wall clock on the host and a
fixed number of ping attempts in the daemon. Raising only the first moved the failure
onto the second instead of letting the guest finish, so the profile now exposes one
duration and the ping loop runs against a deadline built from it.
"""

import pytest

from pysandboxes.remote import parameters
from pysandboxes.remote.parameters import (
    TIMEOUT_FOR_START_DAEMON_QEMU,
    TIMEOUT_FOR_START_DAEMON_QEMU_TCG,
    qemu_start_timeout,
)


@pytest.fixture(autouse=True)
def no_environment_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The defaults are measured without a QEMU_START_TIMEOUT left in the developer's environment."""
    monkeypatch.delenv("QEMU_START_TIMEOUT", raising=False)


@pytest.fixture
def with_kvm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the host offers /dev/kvm, so the default does not follow this machine."""
    monkeypatch.setattr(parameters, "qemu_accel_args", lambda _params: ["-enable-kvm"])


def test_an_absent_rule_keeps_the_default(with_kvm: None) -> None:
    """A KVM boot is served by the default; nothing in a profile should be required."""
    assert qemu_start_timeout({}) == float(TIMEOUT_FOR_START_DAEMON_QEMU)


def test_the_rule_still_wins_without_kvm() -> None:
    """The automatic default is a default, not a ceiling."""
    assert qemu_start_timeout({"use_kvm": "false", "start_timeout": "300"}) == 300.0


def test_a_bad_value_falls_back_to_the_emulated_default_without_kvm() -> None:
    """Falling back to the KVM default here would reintroduce the failure being fixed."""
    assert qemu_start_timeout({"use_kvm": "false", "start_timeout": "soon"}) == float(TIMEOUT_FOR_START_DAEMON_QEMU_TCG)


def test_the_rule_wins_when_it_is_set() -> None:
    """The case this exists for: a host with no /dev/kvm needs ~125s, so it asks for 180."""
    assert qemu_start_timeout({"start_timeout": "180"}) == 180.0


def test_spaces_around_the_value_do_not_matter() -> None:
    assert qemu_start_timeout({"start_timeout": " 120.5 "}) == 120.5


@pytest.mark.parametrize("value", ["", "soon", "0", "-30"])
def test_a_value_that_is_not_a_positive_duration_falls_back(value: str, with_kvm: None) -> None:
    """Waiting forever, or not at all, would be worse than ignoring the rule."""
    assert qemu_start_timeout({"start_timeout": value}) == float(TIMEOUT_FOR_START_DAEMON_QEMU)


def test_the_environment_sets_the_default_when_the_profile_has_no_rule(
    with_kvm: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CI job gives every profile a slower runner's budget without editing each one."""
    monkeypatch.setenv("QEMU_START_TIMEOUT", "180")
    assert qemu_start_timeout({}) == 180.0


def test_the_environment_applies_without_kvm_too(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QEMU_START_TIMEOUT", "400")
    assert qemu_start_timeout({"use_kvm": "false"}) == 400.0


def test_the_profile_rule_wins_over_the_environment(with_kvm: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QEMU_START_TIMEOUT", "180")
    assert qemu_start_timeout({"start_timeout": "45"}) == 45.0


@pytest.mark.parametrize("value", ["", "soon", "0", "-30"])
def test_an_environment_value_that_is_not_a_positive_duration_is_ignored(
    value: str, with_kvm: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QEMU_START_TIMEOUT", value)
    assert qemu_start_timeout({}) == float(TIMEOUT_FOR_START_DAEMON_QEMU)
