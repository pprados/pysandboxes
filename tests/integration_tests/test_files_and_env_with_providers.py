# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What a script can read, write and see of the host, through each backend that confines the filesystem.

``test_guards_with_providers`` proves the call, import and eval guards under every backend. These cases cover
the file and environment rules, where the backend and the Python guard both draw the line. QEMU boots a VM per
run and is left out: the guest has its own filesystem and environment, which is another test.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from ._env import backend_of, coverage_profile_lines, os_sandbox_params, row_profile_lines
from .test_guards_with_providers import _INTERPRETER_PATHS, _TIMEOUT_SECONDS, ROOT_DIR, _skip_unavailable

_ROWS = [row for row in os_sandbox_params() if not str(row.values[0]).startswith("qemu")]


def _run(
    os_sandbox: str, profile_lines: str, script: str, tmp_path: Path, env: dict[str, str] | None = None
) -> "subprocess.CompletedProcess[str]":
    """Run ``script`` from ``tmp_path/app`` under ``python-sb``: only what the profile names is visible."""
    app = tmp_path / "app"
    app.mkdir(exist_ok=True)
    target = app / "script.py"
    target.write_text(script)
    profile = tmp_path / "files.profile"
    exposed = "".join(f"expose-ro={path}\n" for path in (str(app), *_INTERPRETER_PATHS))
    profile.write_text(
        f"py-sandbox=true\nos-sandbox={backend_of(os_sandbox)}\n{row_profile_lines(os_sandbox)}"
        f"python-import=*\n{exposed}{coverage_profile_lines()}{profile_lines}"
    )
    return subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={profile}", str(target)],
        cwd=ROOT_DIR,
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_file_outside_the_rules_is_unreadable_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    _skip_unavailable(os_sandbox)
    secret = tmp_path / "private" / "secret.txt"
    secret.parent.mkdir()
    secret.write_text("top secret")

    done = _run(os_sandbox, "", f"print(open({str(secret)!r}).read())\n", tmp_path)

    assert done.returncode != 0, done.stdout
    assert "top secret" not in done.stdout + done.stderr


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_file_exposed_read_only_is_readable_but_not_writable_under_every_backend(
    os_sandbox: str, tmp_path: Path
) -> None:
    _skip_unavailable(os_sandbox)
    shared = tmp_path / "shared"
    shared.mkdir()
    note = shared / "note.txt"
    note.write_text("hello")
    script = f"print(open({str(note)!r}).read())\nopen({str(note)!r}, 'w').write('changed')\n"

    done = _run(os_sandbox, f"expose-ro={shared}\n", script, tmp_path)

    assert done.returncode != 0, done.stdout
    assert done.stdout.strip() == "hello"
    assert note.read_text() == "hello"


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_directory_exposed_read_write_receives_the_file_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    _skip_unavailable(os_sandbox)
    out = tmp_path / "out"
    out.mkdir()

    done = _run(os_sandbox, f"expose-rw={out}\n", f"open({str(out / 'made.txt')!r}, 'w').write('written')\n", tmp_path)

    assert done.returncode == 0, done.stderr
    assert (out / "made.txt").read_text() == "written"


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_variable_of_the_caller_is_hidden_unless_the_profile_lists_it(os_sandbox: str, tmp_path: Path) -> None:
    _skip_unavailable(os_sandbox)
    script = "import os\nprint(os.environ.get('PYSB_PROBE_SECRET'))\n"

    hidden = _run(os_sandbox, "", script, tmp_path, env={"PYSB_PROBE_SECRET": "visible-to-the-caller"})
    shown = _run(
        os_sandbox,
        "env=PYSB_PROBE_SECRET=${PYSB_PROBE_SECRET}\n",
        script,
        tmp_path,
        env={"PYSB_PROBE_SECRET": "visible-to-the-caller"},
    )

    assert hidden.returncode == 0, hidden.stderr
    assert hidden.stdout.strip() == "None"
    assert shown.returncode == 0, shown.stderr
    assert shown.stdout.strip() == "visible-to-the-caller"
