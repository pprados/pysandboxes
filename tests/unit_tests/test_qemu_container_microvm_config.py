# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Container MicroVM rows explicitly fit the fixed transport budget."""

import shlex
import subprocess
from pathlib import Path

import pytest

from tests.containers_tests.test_containers import _kube_manifest_text, _row_env
from tests.containers_tests import test_containers as containers
from pysandboxes.remote.qemu_sse_daemon import _select_microvm_mounts


@pytest.mark.parametrize("privileged", [True, False])
def test_microvm_container_rows_fit_without_dropping_required_mounts(privileged: bool) -> None:
    env = dict(item.split("=", 1) for item in shlex.split(_row_env("qemu-microvm", privileged)))
    assert env["QEMU_VIRTFS"] == "off"
    # Image topology without staging; only the independent CA share may use guest data.
    paths = [
        "/app",
        "/etc",
        "/app/tmp",
        "/usr/share/ca-certificates",
        "/usr/local/lib",
        "/mnt/pysandbox_run",
        "/usr/local/bin",
    ]
    mounts = [(str(i), Path(path), path) for i, path in enumerate(paths)]
    optional = [path for path in env["QEMU_MICROVM_OPTIONAL_PATHS"].split(",") if path in paths]
    kept, native = _select_microvm_mounts(mounts, optional, 8)
    assert native == ["/usr/share/ca-certificates"]
    assert [guest for _, _, guest in kept] == [
        "/app",
        "/etc",
        "/app/tmp",
        "/usr/local/lib",
        "/mnt/pysandbox_run",
        "/usr/local/bin",
    ]


@pytest.mark.parametrize("privileged", [True, False])
def test_kubernetes_microvm_mode_matches_device_exposure(privileged: bool) -> None:
    manifest = _kube_manifest_text("python-sb-qemu-microvm:latest", privileged, "qemu-microvm")
    assert "name: QEMU_USE_KVM" in manifest
    assert f'value: "{str(privileged).lower()}"' in manifest
    assert ("mountPath: /dev/kvm" in manifest) is privileged
    assert ("path: /dev/kvm" in manifest) is privileged
    assert ("privileged: true" in manifest) is privileged


@pytest.mark.parametrize("runtime", ["docker", "podman"])
def test_microvm_container_scratch_is_private_to_each_run(runtime: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(containers, "_ensure_image", lambda *args: None)
    monkeypatch.setattr(containers, "_qemu_kvm_run_extra_flags", lambda: [])
    monkeypatch.setattr(containers, "_host_dns_servers", lambda: [])
    monkeypatch.setattr(containers, "_add_host_flags", lambda: [])
    monkeypatch.setattr(containers, "_open_ctty", lambda: None)

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(containers.subprocess, "run", run)
    result = containers._run_container_runtime(runtime, "qemu-microvm", False, False)
    cmd = result.args
    assert cmd[cmd.index("--tmpfs") + 1] == "/app/tmp:rw,mode=1777"
    assert cmd[cmd.index("-v") + 1] == f"{containers.ROOT_DIR}:/app"
