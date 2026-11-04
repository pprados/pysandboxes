# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What a real gVisor guest can reach on the host, the Python layer disarmed so only the guest holds.

Each probe runs under ``python-sb`` with ``py-sandbox=false``. A probe that could not fail proves nothing, so
each one is also run without the sandbox, where it must report what the guest is meant to be denied.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from .._env import provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
_SKIP_REASON = provider_skip_reason("gvisor")

pytestmark = pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")


def _profile(tmp_path: Path, *rules: str) -> Path:
    profile = tmp_path / "gvisor.profile"
    lines = [
        "py-sandbox=false",
        "os-sandbox=gvisor",
        "python-import=*",
        "expose-ro=.",
        "expose-ro=/etc",
        f"expose-ro={sys.base_prefix}/lib",
        *rules,
    ]
    profile.write_text("\n".join(lines) + "\n")
    return profile


def _in_guest(tmp_path: Path, code: str, *rules: str, env: dict[str, str] | None = None) -> str:
    cmd = [
        sys.executable,
        "-m",
        "pysandboxes.python_sb",
        f"--pysandboxes-config={_profile(tmp_path, *rules)}",
        "-c",
        code,
    ]
    result = subprocess.run(
        cmd, cwd=ROOT_DIR, env={**os.environ, **(env or {})}, capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


def _on_host(code: str, env: dict[str, str] | None = None) -> str:
    """The negative control: the same probe, with nothing around it."""
    result = subprocess.run(
        [sys.executable, "-c", code], env={**os.environ, **(env or {})}, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr[-3000:]
    return result.stdout


def test_the_guest_runs_on_the_gvisor_kernel_not_on_the_host_one(tmp_path: Path) -> None:
    probe = "import platform; print('RELEASE', platform.release())"

    assert "gvisor" in _in_guest(tmp_path, probe).lower()
    assert "gvisor" not in _on_host(probe).lower(), "the control must report the host kernel"


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


def test_a_path_without_a_rule_does_not_exist_in_the_guest(tmp_path: Path) -> None:
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
    assert "HIDDEN True" in _on_host(probe), "the control: the probe sees it outside the guest"


def test_a_symlink_to_an_unexposed_file_does_not_reach_the_host(tmp_path: Path) -> None:
    exposed, outside = tmp_path / "exposed", tmp_path / "outside"
    exposed.mkdir()
    outside.mkdir()
    (outside / "secret").write_text("SECRET")
    os.symlink(outside / "secret", exposed / "link")
    probe = f"""
try:
    print("READ", open({str(exposed / "link")!r}).read())
except OSError as e:
    print("REFUSED", type(e).__name__)
"""

    assert "REFUSED" in _in_guest(tmp_path, probe, f"expose-ro={exposed}")
    assert "READ SECRET" in _on_host(probe), "the probe reads it outside"


def test_an_ignored_file_inside_an_exposed_directory_is_empty(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET")
    (tmp_path / "other").write_text("VISIBLE")
    probe = (
        f"print('ENV', repr(open({str(tmp_path / '.env')!r}).read()))\n"
        f"print('OTHER', open({str(tmp_path / 'other')!r}).read())"
    )

    out = _in_guest(tmp_path, probe, f"expose-ro={tmp_path}", "ignore=.env")

    assert "OTHER VISIBLE" in out, "the control: the rest of the directory is there"
    assert "ENV ''" in out
    assert "ENV 'SECRET'" in _on_host(probe)


def test_the_host_environment_does_not_leak_into_the_guest(tmp_path: Path) -> None:
    probe = "import os; print('SECRET', os.environ.get('GVISOR_PROBE_SECRET')); print('HOME', os.environ.get('HOME'))"
    env = {"GVISOR_PROBE_SECRET": "leaked"}

    out = _in_guest(tmp_path, probe, env=env)

    assert "SECRET None" in out
    assert "HOME None" in out, "runsc invents HOME=/ when the spec sets none"
    assert "SECRET leaked" in _on_host(probe, env)


def test_the_process_table_of_the_guest_is_its_own(tmp_path: Path) -> None:
    probe = "import os; print('PIDS', len([n for n in os.listdir('/proc') if n.isdigit()]))"

    guest = int(re.search(r"PIDS (\d+)", _in_guest(tmp_path, probe)).group(1))  # type: ignore[union-attr]
    host = int(re.search(r"PIDS (\d+)", _on_host(probe)).group(1))  # type: ignore[union-attr]

    assert guest < 10 < host, f"guest sees {guest} processes, the host {host}"


def _guest_processes() -> set[str]:
    out = subprocess.run(["pgrep", "-af", "runsc.*pysb-"], capture_output=True, text=True).stdout
    return {line.split()[0] for line in out.splitlines() if "pgrep" not in line}


def test_no_runsc_process_outlives_the_run(tmp_path: Path) -> None:
    before = _guest_processes()

    _in_guest(tmp_path, "print('done')")

    assert _guest_processes() - before == set()
