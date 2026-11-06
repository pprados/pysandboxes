# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What a real smolvm guest can reach on the host, the Python layer disarmed so only the guest holds.

A probe that proves the guest holds on its own runs under ``python-sb`` with ``py-sandbox=false``; a probe that could
not fail proves nothing, so each one is also run without the sandbox, or with the protection switched off, where it
must report what the guest is meant to be denied.
"""

import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from .._env import provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
_SKIP_REASON = provider_skip_reason("smolvm")

pytestmark = pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")

# A host the guest is allowed to reach in the network tests, and one it is not. Both are outside the machine.
_ALLOWED_HOST = "example.com"
_DENIED_ADDRESS = "1.1.1.1"
_SYS_ADMIN_BIT = 21


def _profile(tmp_path: Path, *rules: str, os_only: bool) -> Path:
    profile = tmp_path / "smolvm.profile"
    lines = [
        f"py-sandbox={'false' if os_only else 'true'}",
        "os-sandbox=smolvm",
        "python-import=*",
        "expose-ro=.",
        *rules,
    ]
    profile.write_text("\n".join(lines) + "\n")
    return profile


def _in_guest(tmp_path: Path, code: str, *rules: str, os_only: bool = True) -> str:
    cmd = [
        sys.executable,
        "-m",
        "pysandboxes.python_sb",
        f"--pysandboxes-config={_profile(tmp_path, *rules, os_only=os_only)}",
        "-c",
        code,
    ]
    result = subprocess.run(cmd, cwd=ROOT_DIR, capture_output=True, text=True, timeout=180, check=False)
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


def _on_host(code: str) -> str:
    """The negative control: the same probe, with nothing around it."""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


def test_the_guest_runs_on_its_own_kernel_not_on_the_host_one(tmp_path: Path) -> None:
    probe = "import platform; print('RELEASE', platform.release())"

    guest = _in_guest(tmp_path, probe).strip()

    assert guest != f"RELEASE {platform.release()}"
    assert _on_host(probe).strip() == f"RELEASE {platform.release()}", "the control must report the host kernel"


def test_a_read_only_exposure_refuses_writes_and_a_read_write_one_reaches_the_host(tmp_path: Path) -> None:
    read_only, read_write = tmp_path / "ro", tmp_path / "rw"
    read_only.mkdir()
    read_write.mkdir()
    probe = f"""
import pathlib
for name in ({str(read_only)!r}, {str(read_write)!r}):
    try:
        pathlib.Path(name, "written").write_text("x")
        print("WRITTEN", name)
    except OSError as e:
        print("REFUSED", name, type(e).__name__)
"""

    out = _in_guest(tmp_path, probe, f"expose-ro={read_only}", f"expose-rw={read_write}")

    assert f"REFUSED {read_only}" in out
    assert f"WRITTEN {read_write}" in out
    assert not (read_only / "written").exists()
    assert (read_write / "written").read_text() == "x", "the write must land on the host, or the exposure is a copy"


def test_a_path_without_a_rule_holds_nothing_of_the_host(tmp_path: Path) -> None:
    exposed, hidden = tmp_path / "exposed", tmp_path / "hidden"
    exposed.mkdir()
    hidden.mkdir()
    (exposed / "f").write_text("A")
    (hidden / "f").write_text("SECRET")
    probe = f"""
import os
print("EXPOSED", os.path.exists({str(exposed / "f")!r}))
print("HIDDEN", os.path.exists({str(hidden / "f")!r}))
"""

    out = _in_guest(tmp_path, probe, f"expose-ro={exposed}")

    assert "EXPOSED True" in out, "the control: what a rule exposes is there"
    assert "HIDDEN False" in out
    assert "HIDDEN True" in _on_host(probe), "the control sees it"


_CAPABILITIES_PROBE = f"""
cap_eff = int([l for l in open("/proc/self/status") if l.startswith("CapEff")][0].split()[1], 16)
print("SYS_ADMIN", bool(cap_eff >> {_SYS_ADMIN_BIT} & 1))
"""


def test_the_guest_drops_its_capabilities_unless_the_profile_keeps_them(tmp_path: Path) -> None:
    assert "SYS_ADMIN False" in _in_guest(tmp_path, _CAPABILITIES_PROBE)
    assert "SYS_ADMIN True" in _in_guest(tmp_path, _CAPABILITIES_PROBE, "smolvm.unprivileged=false"), "the control"


def _reachable(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=5).close()
    except OSError:
        return False
    return True


_CONNECT = """
import socket
try:
    socket.create_connection(("{host}", 443), timeout=8).close()
    print("CONNECTED")
except OSError as e:
    print("REFUSED", type(e).__name__)
"""


@pytest.mark.skipif(not _reachable(_ALLOWED_HOST, 443), reason=f"{_ALLOWED_HOST} is not reachable from this host")
class TestNetworkFilter:
    @pytest.fixture(scope="class")
    def allowed_ip(self) -> str:
        return socket.gethostbyname(_ALLOWED_HOST)

    def test_a_destination_outside_the_rules_is_dropped_by_the_host_side_of_smolvm(
        self, tmp_path: Path, allowed_ip: str
    ) -> None:
        out = _in_guest(tmp_path, _CONNECT.format(host=_DENIED_ADDRESS), f"net=ALLOW|TCP|{allowed_ip}|*|OUT")

        assert "REFUSED" in out

    def test_the_destination_a_rule_allows_connects(self, tmp_path: Path, allowed_ip: str) -> None:
        """Negative control: the refusal above comes from the filter, not from a guest without a network."""
        out = _in_guest(tmp_path, _CONNECT.format(host=allowed_ip), f"net=ALLOW|TCP|{allowed_ip}|*|OUT")

        assert "CONNECTED" in out

    def test_without_a_rule_the_guest_has_no_network_at_all(self, tmp_path: Path) -> None:
        assert "REFUSED" in _in_guest(tmp_path, _CONNECT.format(host=_DENIED_ADDRESS))
        assert "CONNECTED" in _on_host(_CONNECT.format(host=_DENIED_ADDRESS)), "the control reaches it"


def test_the_environment_of_the_host_does_not_reach_the_guest(tmp_path: Path) -> None:
    probe = "import os; print('SECRET', os.environ.get('SMOLVM_TEST_SECRET'))"
    env = {**os.environ, "SMOLVM_TEST_SECRET": "must-not-reach-the-guest"}

    cmd = [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={_profile(tmp_path, os_only=True)}"]
    guest = subprocess.run([*cmd, "-c", probe], cwd=ROOT_DIR, env=env, capture_output=True, text=True, timeout=180)
    host = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=60)

    assert "SECRET None" in guest.stdout, guest.stderr[-2000:]
    assert "SECRET must-not-reach-the-guest" in host.stdout, "the control sees it"
