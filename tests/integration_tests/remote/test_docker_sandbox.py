# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What a real Docker Sandboxes guest can reach on the host and on the network, the Python layer disarmed.

A probe that proves the guest holds on its own runs under ``python-sb`` with ``py-sandbox=false``; a probe that could
not fail proves nothing, so each one is also run on the host, or against an allowed destination, where it must report
what the guest is meant to be denied. ``sbx`` accepts every handshake and drops what the rules do not allow, so a
destination counts as dropped when the connection raises or its first read ends at once, and as reached only when the
server answers.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from .._env import provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
_SKIP_REASON = provider_skip_reason("docker-sandbox")

pytestmark = pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")

_ALLOWED_HOST = "example.com"
_DENIED_ADDRESS = "1.1.1.1"
_SYS_ADMIN_BIT = 21

# Prints REACHED when the server answers, DROPPED when the connection raises or ends at once, whatever the cause.
_REACH = """
import socket, ssl
def reach(host, port):
    try:
        s = socket.create_connection((host, port), timeout=6)
    except OSError as e:
        return "DROPPED " + type(e).__name__
    try:
        s.settimeout(6)
        if port == 443:
            s = ssl.create_default_context().wrap_socket(s, server_hostname=host)
        s.sendall(b"GET / HTTP/1.0\\r\\nHost: " + host.encode() + b"\\r\\n\\r\\n")
        return "REACHED" if s.recv(16).startswith(b"HTTP/") else "DROPPED eof"
    except OSError as e:
        return "DROPPED " + type(e).__name__
"""


def _profile(tmp_path: Path, *rules: str, os_only: bool) -> Path:
    profile = tmp_path / "docker-sandbox.profile"
    lines = [
        f"py-sandbox={'false' if os_only else 'true'}",
        "os-sandbox=docker-sandbox",
        "python-import=*",
        "expose-ro=.",
        *rules,
    ]
    profile.write_text("\n".join(lines) + "\n")
    return profile


def _run(tmp_path: Path, code: str, *rules: str, os_only: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [
        sys.executable,
        "-m",
        "pysandboxes.python_sb",
        f"--pysandboxes-config={_profile(tmp_path, *rules, os_only=os_only)}",
        "-c",
        code,
    ]
    return subprocess.run(cmd, cwd=ROOT_DIR, capture_output=True, text=True, timeout=240, check=False)


def _in_guest(tmp_path: Path, code: str, *rules: str, os_only: bool = True) -> str:
    result = _run(tmp_path, code, *rules, os_only=os_only)
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


def _on_host(code: str) -> str:
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False)
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


def test_the_guest_runs_on_its_own_kernel_not_on_the_host_one(tmp_path: Path) -> None:
    probe = "import platform; print('RELEASE', platform.release())"

    guest = _in_guest(tmp_path, probe).strip()

    assert guest != _on_host(probe).strip(), "the guest must not report the kernel of the host"


def test_the_payload_runs_as_an_unprivileged_user_with_no_capability(tmp_path: Path) -> None:
    probe = f"""
import os
cap_eff = int([l for l in open("/proc/self/status") if l.startswith("CapEff")][0].split()[1], 16)
print("SYS_ADMIN", bool(cap_eff >> {_SYS_ADMIN_BIT} & 1))
print("UID", os.getuid())
print("HOME", os.path.expanduser("~"))
"""

    out = _in_guest(tmp_path, probe)

    assert "SYS_ADMIN False" in out and "UID 2000" in out
    assert "HOME /" in out, "the passwd entry must give the user a home"
    assert f"UID {os.getuid()}" in _on_host(probe), "the control: the host user is not the payload user"


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

    assert f"REFUSED {read_only}" in out and f"WRITTEN {read_write}" in out
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

    assert "EXPOSED True" in out and "HIDDEN False" in out
    assert "HIDDEN True" in _on_host(probe), "the control sees it"


def test_an_ignore_rule_hides_a_file_inside_an_exposed_directory_even_to_native_code(tmp_path: Path) -> None:
    exposed = tmp_path / "exposed"
    exposed.mkdir()
    (exposed / ".env").write_text("SECRET")
    (exposed / "other.txt").write_text("VISIBLE")
    probe = f"""
import ctypes
libc = ctypes.CDLL(None, use_errno=True)
for name in ("{exposed}/.env", "{exposed}/other.txt"):
    fd = libc.open(name.encode(), 0)
    print("OPEN", name.rsplit("/", 1)[1], fd >= 0)
    if fd >= 0:
        buf = ctypes.create_string_buffer(16)
        count = libc.read(fd, buf, 16)
        print("READ", name.rsplit("/", 1)[1], buf.raw[: max(count, 0)])
"""

    out = _in_guest(tmp_path, probe, f"expose-ro={exposed}", "ignore=.env")

    assert "READ other.txt b'VISIBLE'" in out, "the control: what is not ignored is readable"
    assert "SECRET" not in out


def test_the_environment_of_the_host_does_not_reach_the_guest(tmp_path: Path) -> None:
    probe = "import os; print('LEAK', os.environ.get('PYSB_DOCKER_SANDBOX_SECRET'))"
    env = {**os.environ, "PYSB_DOCKER_SANDBOX_SECRET": "leaked"}
    cmd = [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={_profile(tmp_path, os_only=True)}"]

    guest = subprocess.run([*cmd, "-c", probe], cwd=ROOT_DIR, env=env, capture_output=True, text=True, timeout=240)

    assert "LEAK None" in guest.stdout, guest.stderr[-2000:]
    control = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True, timeout=60)
    assert "LEAK leaked" in control.stdout, "the control: without the sandbox the variable is visible"


def test_the_exit_status_and_the_two_streams_come_back(tmp_path: Path) -> None:
    result = _run(tmp_path, "import sys; print('out'); print('err', file=sys.stderr); sys.exit(7)")

    assert result.returncode == 7
    assert result.stdout.strip() == "out" and "err" in result.stderr


def test_a_run_leaves_no_sandbox_behind(tmp_path: Path) -> None:
    _in_guest(tmp_path, "print('x')")

    listing = subprocess.run(["sbx", "ls", "--quiet"], capture_output=True, text=True, timeout=60, check=False)

    assert not [name for name in listing.stdout.split() if name.startswith("pysb-") and str(os.getpid()) in name]


class TestNetwork:
    """The OS filter alone, against real destinations outside the machine."""

    def _rule(self, host: str = _ALLOWED_HOST, port: int = 443) -> str:
        return f"net=ALLOW|tcp|{host}|{port}|OUT"

    def test_the_destination_a_rule_allows_is_reached(self, tmp_path: Path) -> None:
        out = _in_guest(tmp_path, _REACH + f"print(reach({_ALLOWED_HOST!r}, 443))", self._rule())

        assert "REACHED" in out, "the negative control: an allowed destination must answer"

    @pytest.mark.parametrize(
        ("host", "port"),
        [(_ALLOWED_HOST, 80), (_DENIED_ADDRESS, 443), (_DENIED_ADDRESS, 81), ("www.example.org", 443)],
        ids=["other-port", "other-address", "closed-port", "other-name"],
    )
    def test_a_destination_outside_the_rules_is_dropped(self, tmp_path: Path, host: str, port: int) -> None:
        code = _REACH + f"print(reach({_ALLOWED_HOST!r}, 443)); print(reach({host!r}, {port}))"

        out = _in_guest(tmp_path, code, self._rule()).splitlines()

        assert out[-2] == "REACHED", "the control must reach the allowed destination in the same run"
        assert out[-1].startswith("DROPPED"), out

    def test_without_a_rule_nothing_is_reached(self, tmp_path: Path) -> None:
        out = _in_guest(tmp_path, _REACH + f"print(reach({_ALLOWED_HOST!r}, 443))")

        assert out.strip().startswith("DROPPED")

    def test_the_proxy_variables_reach_the_payload_only_when_asked(self, tmp_path: Path) -> None:
        probe = "import os; print('PROXY', os.environ.get('HTTPS_PROXY'))"

        default = _in_guest(tmp_path, probe)
        asked = _in_guest(tmp_path, probe, "docker-sandbox.proxy=true", self._rule())

        assert "PROXY None" in default
        assert "PROXY http://gateway.docker.internal:3128" in asked
