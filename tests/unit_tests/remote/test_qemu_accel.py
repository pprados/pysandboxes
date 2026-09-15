# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""``qemu.use_kvm`` has to actually reach the QEMU command line.

The integration suite runs every scenario twice, on the ``qemu`` row and on the
``qemu-tcg`` one, to cover both acceleration and emulation. That pair only means
something if the rule switches something: were ``use_kvm=false`` ignored, the two
rows would run the same configuration twice and stay green while covering half of
what they claim. These tests are what makes the second row a second case.

They are unit tests on purpose. Observing the difference for real costs a VM boot
each way -- measured at 12s accelerated against 102s emulated -- and the thing
worth pinning is a flag, not a boot.
"""

from collections.abc import Mapping

import pytest  # type: ignore[import-untyped]

from pysandboxes.remote import qemu_image
from pysandboxes.remote.qemu_image import qemu_accel_args


@pytest.fixture
def host_with_kvm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qemu_image, "is_kvm_available", lambda: True)


@pytest.fixture
def host_without_kvm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qemu_image, "is_kvm_available", lambda: False)


@pytest.mark.parametrize("value", ["true", "True", "1", "yes"])
def test_acceleration_is_asked_for_and_granted(value: str, host_with_kvm: None) -> None:
    """The profile asks, the host can: QEMU is told to accelerate."""
    assert qemu_accel_args({"use_kvm": value}) == ["-enable-kvm"]


def test_acceleration_is_the_default(host_with_kvm: None) -> None:
    """A profile naming no qemu rule at all still gets the fast path."""
    assert qemu_accel_args({}) == ["-enable-kvm"]


@pytest.mark.parametrize("value", ["false", "False", "0", "no", ""])
def test_a_profile_can_refuse_acceleration(value: str, host_with_kvm: None) -> None:
    """``use_kvm=false`` drops the flag even where /dev/kvm is there.

    This is the row the integration suite calls "qemu-tcg": a developer machine
    has KVM, so without this the emulated configuration would never be exercised
    outside a container.
    """
    assert qemu_accel_args({"use_kvm": value}) == []


def test_a_host_without_kvm_falls_back_to_emulation(host_without_kvm: None) -> None:
    """No /dev/kvm -- a container, typically -- runs TCG rather than failing."""
    assert qemu_accel_args({"use_kvm": "true"}) == []


def test_other_qemu_rules_do_not_decide_acceleration(host_with_kvm: None) -> None:
    """Only use_kvm speaks here; the neighbouring qemu.* rules are read elsewhere."""
    params: Mapping[str, str] = {"memory": "4G", "show_boot_console": "true"}
    assert qemu_accel_args(params) == ["-enable-kvm"]
