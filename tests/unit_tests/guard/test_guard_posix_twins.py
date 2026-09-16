# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""`os` re-exports its file calls; patching only `os` leaves the twin open.

`os.open is posix.open` holds until something patches one of them, because `os`
does not implement these calls -- it re-exports them from `posix` on every
POSIX platform, from `nt` on Windows. So a rule table naming only `os.*` can be
walked around with one `import posix`, which is not an exotic manoeuvre: the
module is documented, importable, and what `os` itself uses.

Measured before the twins were added: `open()` on a path outside the exposed
directory raised RuleFileNotFoundError while `posix.open()` on that same path
reached the kernel.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.guard_files import patch_rules

TWIN = "nt" if sys.platform == "win32" else "posix"


def test_every_reexported_os_rule_has_a_twin() -> None:
    """A rule on `os.X` is worth nothing while `<twin>.X` is the same object."""
    rules = patch_rules(learn=False)
    twin_module = __import__(TWIN)

    missing = [
        key
        for key in rules
        if key.startswith("os.") and hasattr(twin_module, key[3:]) and f"{TWIN}.{key[3:]}" not in rules
    ]

    assert not missing, f"os rules with an unguarded twin: {missing}"


def test_the_twin_rule_reuses_the_os_factory() -> None:
    """Same wrapper both sides, or the twin enforces something else."""
    rules = patch_rules(learn=False)

    twins = {key for key in rules if key.startswith(f"{TWIN}.")}
    assert twins, "no twin rule was generated at all"

    for key in twins:
        assert rules[key] is rules[f"os.{key.split('.', 1)[1]}"]


def test_a_rule_that_os_owns_itself_gets_no_twin() -> None:
    """`os.getcwd` is re-exported, but e.g. `os.walk` is pure Python.

    Mirroring a name the twin does not provide would post a patch on nothing.
    """
    rules = patch_rules(learn=False)
    twin_module = __import__(TWIN)

    for key in rules:
        if key.startswith(f"{TWIN}."):
            assert hasattr(twin_module, key.split(".", 1)[1])


@pytest.mark.skipif(sys.platform == "win32", reason="probe script assumes posix")
def test_posix_open_is_refused_like_builtin_open(tmp_path: Path) -> None:
    """The point of the whole change, end to end under `python-sb`.

    Run out of process: the twins are posted by the import hook, so this needs
    a real interpreter start rather than a table inspection.
    """
    work = tmp_path / "work"
    work.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("classified\n")
    (work / ".py-sandboxes").write_text(
        "py-sandbox=true\nos-sandbox=subprocess\npython-import=*\n" f"expose-rw={work}\nexpose-ro={Path.cwd()}\n"
    )
    (work / "probe.py").write_text(
        "import os\n"
        "import posix\n"
        "from pysandboxes.e import SandBoxError\n"
        f"target = {str(secret)!r}\n"
        'for tag, call in (("open", lambda: open(target).close()),\n'
        '                 ("posix.open", lambda: posix.close(posix.open(target, 0)))):\n'
        "    try:\n"
        "        call()\n"
        "        print(tag, 'ALLOWED')\n"
        "    except SandBoxError:\n"
        "        print(tag, 'GUARD')\n"
        "    except BaseException as exc:\n"
        "        print(tag, 'OTHER', type(exc).__name__)\n"
    )

    result = subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", "probe.py"],
        capture_output=True,
        text=True,
        cwd=work,
        env={**os.environ, "TMPDIR": str(work)},
    )

    assert "open GUARD" in result.stdout, result.stdout + result.stderr
    assert "posix.open GUARD" in result.stdout, result.stdout + result.stderr
