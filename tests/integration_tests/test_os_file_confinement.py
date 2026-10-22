# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The file confinement of each OS provider, with the Python guards off.

``py-sandbox=false`` removes every Python guard, so a refused read or write can only come from the provider. Each row
runs in both launch modes, `python-sb` and the daemon, and starts from a control: the same operations succeed here,
outside any sandbox, so a refusal in the sandbox is not a permission of the host.
"""

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from ._env import backend_of, os_sandbox_params, provider_skip_reason

ROOT_DIR = Path(__file__).resolve().parent.parent.parent

_EXPECTED = {
    "ro_read": "ALLOWED",
    "ro_write": "DENIED",
    "outside_read": "DENIED",
    "rw_write": "ALLOWED",
}


def _params() -> list:
    """The OS providers, without `subprocess`, which has no file boundary to verify."""
    return [
        pytest.param(row.values[0], mode, marks=[*row.marks, pytest.mark.skipif(bool(reason), reason=reason or "")])
        for row in os_sandbox_params()
        if row.values[0] != "subprocess"
        for reason in (provider_skip_reason(backend_of(row.values[0])),)
        for mode in ("python-sb", "daemon")
    ]


@pytest.fixture
def files_dir() -> Iterator[Path]:
    """A directory outside the system temporary directory, which Landlock opens whole to the sandbox."""
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        yield Path(directory).resolve()


def _run(tmp_path: Path, files_dir: Path, row: str, mode: str) -> tuple[dict[str, str], Path]:
    ro_dir, rw_dir, outside_dir = files_dir / "ro", files_dir / "rw", files_dir / "outside"
    for directory in (ro_dir, rw_dir, outside_dir):
        directory.mkdir()
    ro_file, outside_file = ro_dir / "readable.txt", outside_dir / "secret.txt"
    ro_file.write_text("readable")
    outside_file.write_text("secret")
    paths = [str(ro_file), str(ro_dir), str(outside_file), str(rw_dir)]

    # The control: the host lets the same operations through.
    assert ro_file.read_text() == "readable"
    assert outside_file.read_text() == "secret"
    (ro_dir / "control.txt").write_text("written")

    profile = tmp_path / "files.profile"
    profile.write_text(
        "".join(
            [
                "py-sandbox=false\n",
                f"os-sandbox={backend_of(row)}\n",
                "qemu.use_kvm=false\n" if row == "qemu-tcg" else "",
                "python-import=*\n",
                "expose-ro=.\n",
                "expose-ro=/etc\n",
                f"expose-ro={sys.base_prefix}/lib\n",
                f"expose-ro={ro_dir}\n",
                f"expose-rw={rw_dir}\n",
            ]
        )
    )
    plain = ["--plain"] if mode == "python-sb" else []
    probe = ["-m", "tests.integration_tests.tst_file_probe", *plain, str(profile), *paths]
    cmd = (
        [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={profile}", *probe]
        if mode == "python-sb"
        else [sys.executable, *probe]
    )
    env = {**os.environ, "QEMU_USE_KVM": os.environ.get("QEMU_USE_KVM", "true")}
    result = subprocess.run(cmd, cwd=ROOT_DIR, env=env, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr[-3000:]
    return json.loads(result.stdout.strip().splitlines()[-1]), rw_dir


@pytest.mark.parametrize(("row", "mode"), _params())
def test_the_provider_alone_confines_the_files(tmp_path: Path, files_dir: Path, row: str, mode: str) -> None:
    outcomes, rw_dir = _run(tmp_path, files_dir, row, mode)

    assert {name: outcome.split()[0] for name, outcome in outcomes.items()} == _EXPECTED, outcomes
    assert (rw_dir / "created.txt").read_text() == "written"
