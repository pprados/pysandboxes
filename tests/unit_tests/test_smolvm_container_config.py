# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The smolvm container rows: what the pod and the run command grant, and what they must not."""

import pytest

from tests.containers_tests import test_containers as containers
from tests.containers_tests.test_containers import _kube_manifest_text


def test_a_privileged_pod_receives_the_kvm_device_as_a_host_path() -> None:
    text = _kube_manifest_text("python-sb-smolvm:latest", True, "smolvm")

    assert "privileged: true" in text
    assert "path: /dev/kvm" in text
    assert containers._KVM_RESOURCE not in text


def test_an_unprivileged_pod_asks_the_device_plugin_and_grants_nothing_else() -> None:
    """The row proves smolvm runs without privileges: any privilege left in the pod would make it pass for nothing."""
    text = _kube_manifest_text("python-sb-smolvm:latest", False, "smolvm")

    assert f"{containers._KVM_RESOURCE}: 1" in text
    for granted in ("privileged:", "capabilities:", "seccompProfile", "appArmorProfile", "path: /dev/kvm"):
        assert granted not in text, f"an unprivileged smolvm pod must not carry {granted!r}"


@pytest.mark.parametrize("os_sandbox", ["bwrap", "unshare", "gvisor", "landlock", "qemu"])
def test_the_other_providers_pods_do_not_ask_for_the_kvm_device_plugin(os_sandbox: str) -> None:
    for privileged in (True, False):
        assert containers._KVM_RESOURCE not in _kube_manifest_text("python-sb:latest", privileged, os_sandbox)


def test_the_device_plugin_manifest_names_the_resource_the_pods_ask_for() -> None:
    manifest = containers.KVM_DEVICE_PLUGIN_MANIFEST.read_text(encoding="utf-8")
    domain, name = containers._KVM_RESOURCE.split("/")

    assert f"- {domain}" in manifest
    assert f"name: {name}" in manifest
    assert "privileged: true" not in manifest, "the plugin itself must not need privileges either"
