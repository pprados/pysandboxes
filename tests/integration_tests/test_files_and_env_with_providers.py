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


_ENV_ROUTES_SCRIPT = """\
import glob
import os
import posix
import subprocess

needle = {needle!r}
name = {name!r}
leaks = []


def probe(route, read):
    try:
        data = read()
    except BaseException:
        return
    if needle in (data if isinstance(data, str) else repr(data)):
        leaks.append(route)


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode(errors="replace")


probe("os.environ", lambda: dict(os.environ))
probe("os.environb", lambda: dict(os.environb))
probe("os.getenv", lambda: os.getenv(name))
probe("posix.environ", lambda: posix.environ)
probe("/proc/self/environ", lambda: read_text("/proc/self/environ"))
probe("/proc/<parent>/environ", lambda: read_text(f"/proc/{{os.getppid()}}/environ"))
probe("/proc/*/environ", lambda: "".join(read_text(p) for p in glob.glob("/proc/[0-9]*/environ")))
probe("subprocess env", lambda: subprocess.run(["env"], capture_output=True, text=True).stdout)
print("LEAKS=" + ",".join(leaks))
"""


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_hidden_variable_is_not_reachable_by_any_other_route_under_every_backend(
    os_sandbox: str, tmp_path: Path
) -> None:
    _skip_unavailable(os_sandbox)
    name = "PYSB_PROBE_HIDDEN"
    needle = "hidden-value-8f3a1c"
    script = _ENV_ROUTES_SCRIPT.format(needle=needle, name=name)

    done = _run(os_sandbox, "", script, tmp_path, env={name: needle})

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().splitlines()[-1] == "LEAKS=", done.stdout
    assert needle not in done.stdout + done.stderr


_DIR_FD_SCRIPT = """\
import os
import shutil

fd = os.open({directory!r}, os.O_RDONLY | os.O_DIRECTORY)
print("stat", os.stat("seed.txt", dir_fd=fd).st_size)
os.mkdir("made", dir_fd=fd)
print("mkdir allowed")
shutil.rmtree({tree!r})
print("rmtree done")
"""


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_directory_descriptor_is_resolved_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """The guard resolves ``dir_fd`` through ``/proc/self/fd``: a backend that hides ``/proc`` would deny it."""
    _skip_unavailable(os_sandbox)
    rw = tmp_path / "rw"
    (rw / "tree" / "inner").mkdir(parents=True)
    (rw / "seed.txt").write_text("seed")
    script = _DIR_FD_SCRIPT.format(directory=str(rw), tree=str(rw / "tree"))

    done = _run(os_sandbox, f"expose-rw={rw}\n", script, tmp_path)

    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["stat 4", "mkdir allowed", "rmtree done"], done.stdout
    assert (rw / "made").is_dir()
    assert not (rw / "tree").exists()


@pytest.mark.parametrize("os_sandbox", _ROWS)
def test_a_directory_descriptor_does_not_write_into_a_read_only_directory_under_every_backend(
    os_sandbox: str, tmp_path: Path
) -> None:
    _skip_unavailable(os_sandbox)
    ro = tmp_path / "ro"
    ro.mkdir()
    (ro / "seed.txt").write_text("seed")
    script = (
        f"import os\nfd = os.open({str(ro)!r}, os.O_RDONLY | os.O_DIRECTORY)\n"
        "print(os.stat('seed.txt', dir_fd=fd).st_size)\nos.mkdir('made', dir_fd=fd)\n"
    )

    done = _run(os_sandbox, f"expose-ro={ro}\n", script, tmp_path)

    assert done.returncode != 0, done.stdout
    assert done.stdout.strip() == "4", done.stderr
    assert not (ro / "made").exists()
