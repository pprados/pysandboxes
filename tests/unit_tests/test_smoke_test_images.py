# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Tests of .github/scripts/smoke-test-images.sh, run by the images job of release.yml before any push."""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / ".github" / "scripts" / "smoke-test-images.sh"
VERSION = "0.1.0b5"
IMAGES = [
    "python-sb",
    "python-sb-landlock",
    "python-sb-unshare",
    "python-sb-bwrap",
    "python-sb-qemu",
    "python-sb-qemu-microvm",
    "python-sb-gvisor",
    "python-sb-smolvm",
]

# Stands for docker: logs `run --rm <image> <command...>`; prints the version held in $FAKE_DIR/version-<image>
# (else $FAKE_VERSION) for the importlib.metadata probe; fails when "<image> <command>" is listed in $FAKE_DIR/broken.
FAKE_DOCKER = """#!/usr/bin/env bash
shift
flags=""
while [[ $1 == -* ]]; do
    flags+="$1 "
    if [[ $1 == --device || $1 == --group-add || $1 == --network || $1 == --user ]]; then shift; fi
    shift
done
image=${1%%:*}; shift
printf '%s %s\\n' "$image" "$*" >>"$FAKE_DIR/calls"
printf '%s %s\\n' "$image" "$flags" >>"$FAKE_DIR/flags"
if grep -qxF "$image $1" "$FAKE_DIR/broken" 2>/dev/null; then exit 1; fi
if [[ $1 == sh && $3 == *guest-ok* ]]; then
    grep -qxF -e "guest" -e "guest-$image" "$FAKE_DIR/broken" 2>/dev/null || echo guest-ok
    exit 0
fi
if [[ $1 == python && $2 == -c ]]; then
    cat "$FAKE_DIR/version-$image" 2>/dev/null || echo "$FAKE_VERSION"
fi
"""


@pytest.fixture
def fake(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    return tmp_path


def _smoke(fake: Path, kvm: str = "/dev/null") -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PATH": f"{fake / 'bin'}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "FAKE_VERSION": VERSION,
        "KVM_DEVICE": kvm,
    }
    return subprocess.run([str(SCRIPT), VERSION, "3.13"], env=env, capture_output=True, text=True, check=False)


def _calls(fake: Path) -> list[str]:
    return (fake / "calls").read_text().splitlines()


def test_six_sound_images_pass(fake: Path) -> None:
    assert _smoke(fake).returncode == 0


def test_every_image_is_probed_for_its_version_and_its_cli(fake: Path) -> None:
    _smoke(fake)
    calls = _calls(fake)
    for image in IMAGES:
        assert any(c.startswith(f"{image} python -c") and "importlib.metadata" in c for c in calls)
        assert f"{image} python-sb --help" in calls


# Every binary the provider invokes, not only the one it is named after: without iptables-restore or nsenter, a
# profile with socket rules cannot start.
PROVIDER_TOOLS = [
    "python-sb-unshare unshare --version",
    "python-sb-unshare iptables --version",
    "python-sb-unshare iptables-restore --version",
    "python-sb-unshare ip -V",
    "python-sb-unshare slirp4netns --version",
    "python-sb-bwrap bwrap --version",
    "python-sb-bwrap iptables-restore --version",
    "python-sb-bwrap slirp4netns --version",
    "python-sb-bwrap nsenter --version",
    "python-sb-qemu qemu-system-x86_64 --version",
    "python-sb-qemu genisoimage --version",
    "python-sb-qemu-microvm qemu-system-x86_64 --version",
    "python-sb-qemu-microvm genisoimage --version",
    "python-sb-gvisor runsc --version",
    "python-sb-gvisor ls /usr/bin/gvisor-bin/gvisor_sentry",
    "python-sb-gvisor unshare --version",
    "python-sb-gvisor iptables-restore --version",
    "python-sb-gvisor ip -V",
    "python-sb-gvisor slirp4netns --version",
    "python-sb-smolvm smolvm --version",
    "python-sb-smolvm ls /opt/smolvm/guest.tar",
]


def test_each_provider_image_runs_every_tool_it_invokes(fake: Path) -> None:
    _smoke(fake)
    calls = _calls(fake)
    for call in PROVIDER_TOOLS:
        assert call in calls
    assert any(c.startswith("python-sb-qemu sh -c") and "PYSANDBOXES_VM_IMAGES_DIR" in c for c in calls)
    assert any(c.startswith("python-sb-qemu-microvm sh -c") and "PYSANDBOXES_VM_IMAGES_DIR" in c for c in calls)
    assert any(c.startswith("python-sb-qemu-microvm python -c") and "ensure_microvm_boot_artifacts" in c for c in calls)


def test_an_image_holding_another_version_fails(fake: Path) -> None:
    (fake / "version-python-sb-bwrap").write_text("0.1.0b4\n")
    result = _smoke(fake)
    assert result.returncode == 1
    assert "python-sb-bwrap" in result.stdout


@pytest.mark.parametrize(
    "broken",
    [" ".join(call.split()[:2]) for call in PROVIDER_TOOLS] + ["python-sb-qemu sh"],
)
def test_a_missing_provider_binary_fails(fake: Path, broken: str) -> None:
    (fake / "broken").write_text(broken + "\n")
    assert _smoke(fake).returncode != 0


def test_the_qemu_guest_runs_a_program_behind_a_network_rule(fake: Path) -> None:
    _smoke(fake)
    probe = [c for c in _calls(fake) if c.startswith("python-sb-qemu sh -c printf")]
    assert len(probe) == 1
    assert "os-sandbox=qemu" in probe[0]
    assert "net=ALLOW|TCP" in probe[0]


def test_the_microvm_guest_runs_a_program_behind_a_network_rule(fake: Path) -> None:
    _smoke(fake)
    probe = [c for c in _calls(fake) if c.startswith("python-sb-qemu-microvm sh -c printf")]
    assert len(probe) == 1
    assert "os-sandbox=qemu-microvm" in probe[0]
    assert "net=ALLOW|TCP" in probe[0]


def test_the_smolvm_guest_runs_a_program_with_no_privilege(fake: Path) -> None:
    _smoke(fake)
    probe = [c for c in _calls(fake) if c.startswith("python-sb-smolvm sh -c printf")]
    assert len(probe) == 1
    assert "os-sandbox=smolvm" in probe[0]
    flags = [line for line in (fake / "flags").read_text().splitlines() if line.startswith("python-sb-smolvm ")]
    run = [line for line in flags if "--device" in line]
    assert len(run) == 1
    assert "--user" in run[0] and "--group-add" in run[0], "a user of the group of the device"
    assert "--privileged" not in run[0], "the point of the check is that no privilege is needed"


def test_a_smolvm_guest_that_does_not_run_fails(fake: Path) -> None:
    (fake / "broken").write_text("guest-python-sb-smolvm\n")
    result = _smoke(fake)
    assert result.returncode == 1
    assert "the smolvm guest of python-sb-smolvm" in result.stdout, "the qemu guests ran and only smolvm failed"


def test_a_guest_that_cannot_apply_its_network_rules_fails(fake: Path) -> None:
    (fake / "broken").write_text("guest\n")
    result = _smoke(fake)
    assert result.returncode == 1
    assert "cannot apply its network rules" in result.stdout


def test_without_kvm_the_guest_is_not_run_and_the_smoke_test_warns(fake: Path) -> None:
    result = _smoke(fake, kvm=str(fake / "no-kvm"))
    assert result.returncode == 0
    assert "::warning::" in result.stdout
    assert not any(c.startswith("python-sb-qemu sh -c printf") for c in _calls(fake))
    assert not any(c.startswith("python-sb-qemu-microvm sh -c printf") for c in _calls(fake))
    assert not any(c.startswith("python-sb-smolvm sh -c printf") for c in _calls(fake))
