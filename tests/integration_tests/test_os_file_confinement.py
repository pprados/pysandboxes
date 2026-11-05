# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The file confinement of each OS provider, with the Python guards off.

``py-sandbox=false`` removes every Python guard, so a refused read or write can only come from the provider. Each row
runs in both launch modes, `python-sb` and the daemon, and starts from a control: the same operations succeed here,
outside any sandbox, so a refusal in the sandbox is not a permission of the host.

The sandbox is also given a temporary directory of its own: a host file in ``/tmp`` stays out of its reach, and
``tempfile`` still works.
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from ._env import backend_of, os_sandbox_params, provider_skip_reason, row_profile_lines

from .tst_file_probe import _native_read, _native_open_write

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

_EXPECTED = {
    "ro_read": "ALLOWED",
    "ro_write": "DENIED",
    "outside_read": "DENIED",
    "rw_write": "ALLOWED",
    "host_tmp_read": "DENIED",
    "own_tmp_write": "ALLOWED",
}


def _params() -> list:
    """The OS providers, without `subprocess`, which has no file boundary to verify."""
    return [
        pytest.param(row.values[0], mode, marks=[*row.marks, pytest.mark.skipif(bool(reason), reason=reason or "")])
        for row in os_sandbox_params()
        if row.values[0] != "subprocess"
        for reason in (provider_skip_reason(row.values[0]),)
        for mode in ("python-sb", "daemon")
    ]


@pytest.fixture
def host_tmp_file() -> Iterator[Path]:
    """A file in the host's shared ``/tmp``, which no rule exposes."""
    with tempfile.NamedTemporaryFile(dir="/tmp", prefix="host-secret-", suffix=".txt", delete=False) as handle:
        handle.write(b"host secret")
    path = Path(handle.name)
    yield path
    path.unlink(missing_ok=True)


def _run(tmp_path: Path, host_tmp_file: Path, row: str, mode: str) -> tuple[dict[str, str], Path]:
    native = backend_of(row) == "qemu-microvm"
    ro_dir = ROOT_DIR if native else tmp_path / "ro"
    rw_dir, outside_dir = tmp_path / "rw", tmp_path / "outside"
    for directory in (ro_dir, rw_dir, outside_dir):
        directory.mkdir(exist_ok=True)
    ro_file = ROOT_DIR / "pyproject.toml" if native else ro_dir / "readable.txt"
    outside_file = outside_dir / "secret.txt"
    if not native:
        ro_file.write_text("readable")
    outside_file.write_text("secret")
    paths = [str(ro_file), str(ro_dir), str(outside_file), str(rw_dir), str(host_tmp_file)]

    # The control: the host lets the same operations through.
    if not native:
        assert ro_file.read_text() == "readable"
    assert outside_file.read_text() == "secret"
    assert host_tmp_file.read_text() == "host secret"
    if backend_of(row) == "qemu-microvm":
        _native_read(str(ro_file))
        assert _native_read(str(ROOT_DIR / "README.md")), "ignore sentinel must contain original bytes"
        _native_read(str(outside_file))
        _native_read(str(host_tmp_file))
        _native_open_write(str(ro_file))
    else:
        (ro_dir / "control.txt").write_text("written")

    profile = tmp_path / "files.profile"
    profile.write_text(
        "".join(
            [
                "py-sandbox=false\n",
                f"os-sandbox={backend_of(row)}\n",
                row_profile_lines(row),
                "python-import=*\n",
                "expose-ro=.\n",
                "expose-ro=/etc\n",
                f"expose-ro={sys.base_prefix}/lib\n",
                f"expose-ro={ro_dir}\n",
                "ignore=README.md\n" if backend_of(row) == "qemu-microvm" else "",
                f"expose-rw={rw_dir}\n",
            ]
        )
    )
    plain = ["--plain"] if mode == "python-sb" else []
    if backend_of(row) == "qemu-microvm":
        plain.append("--native")
        paths.append(hashlib.sha256((ROOT_DIR / "README.md").read_bytes()).hexdigest())
    probe = ["-m", "tests.integration_tests.tst_file_probe", *plain, str(profile), *paths]
    cmd = (
        [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={profile}", *probe]
        if mode == "python-sb"
        else [sys.executable, *probe]
    )
    env = {**os.environ, "QEMU_USE_KVM": os.environ.get("QEMU_USE_KVM", "true"), "MICROVM_HOST_SECRET": "host-secret"}
    result = subprocess.run(cmd, cwd=ROOT_DIR, env=env, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1]), rw_dir


@pytest.mark.parametrize(("row", "mode"), _params())
def test_the_provider_alone_confines_the_files(tmp_path: Path, host_tmp_file: Path, row: str, mode: str) -> None:
    outcomes, rw_dir = _run(tmp_path, host_tmp_file, row, mode)

    expected = dict(_EXPECTED)
    if backend_of(row) == "qemu-microvm":
        expected.update(ignored_read="DENIED", env_secret="DENIED")
    assert {name: outcome.split()[0] for name, outcome in outcomes.items()} == expected, outcomes
    assert (rw_dir / "created.txt").read_text() == "written"
