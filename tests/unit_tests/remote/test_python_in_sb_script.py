# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""A user script must run with the globals CPython would give it.

``exec(source)`` called from inside a function uses that function's
``globals()`` *and* its ``locals()``, which are two different mappings. The
script's assignments land in the caller's locals, while any function the script
defines captures ``python_in_sb``'s globals as its ``__globals__``. The script
then runs, prints, and only fails when one of its own functions reads one of
its own module-level names -- ordinary code, broken in a way that points at the
wrong place.
"""

import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest  # type: ignore[import-untyped]

from pysandboxes.all_rules import AllRules
from pysandboxes.remote.python_in_sb import _python_command, _python_script

# Both entry points read all_rules on one branch only -- the interactive prompt, under
# ``sys.flags.inspect`` -- which a test run never takes. Passing a real AllRules would
# mean building one to have it ignored.
_UNUSED_RULES = cast(AllRules, ())

_SCRIPT = """\
CONST = 42


def read_it():
    return CONST


assert read_it() == 42, "a function cannot see its own module global"
print("__name__:", __name__)
print("__file__:", __file__)
"""


def test_a_function_sees_its_module_globals(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """The defining bug: ``read_it()`` raised ``NameError: CONST``."""
    script = tmp_path / "witness.py"
    script.write_text(_SCRIPT)

    assert _python_script(_UNUSED_RULES, script, []) == 0

    assert "__name__: __main__" in capsys.readouterr().out


def test_the_script_is_named_main_and_knows_its_file(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """``python script.py`` sets both; so must ``python-sb script.py``."""
    script = tmp_path / "witness.py"
    script.write_text(_SCRIPT)

    _python_script(_UNUSED_RULES, script, [])

    out = capsys.readouterr().out
    assert "__name__: __main__" in out
    assert f"__file__: {script}" in out


def test_a_file_the_script_cannot_open_is_not_reported_as_the_script(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Only reading the script is CPython's "can't open file": a refusal inside it propagates."""
    script = tmp_path / "reader.py"
    script.write_text(f"open({str(tmp_path / 'absent.txt')!r})\n")

    with pytest.raises(FileNotFoundError, match="absent.txt"):
        _python_script(_UNUSED_RULES, script, [])

    assert "can't open file" not in capsys.readouterr().err


def test_a_missing_script_is_reported_like_cpython(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert _python_script(_UNUSED_RULES, tmp_path / "missing.py", []) == 2

    assert "can't open file" in capsys.readouterr().err


def test_dash_c_also_gets_a_single_namespace(capsys: pytest.CaptureFixture) -> None:
    """``python-sb -c`` runs through ``_python_command`` and has the same bug."""
    assert _python_command(_UNUSED_RULES, "C = 1\ndef f():\n    return C\nassert f() == 1\n", []) == 0


def test_a_traceback_names_the_script_not_string(tmp_path: Path) -> None:
    """Compiling with the real path makes failures point at the user's file."""
    script = tmp_path / "boom.py"
    script.write_text("raise ValueError('boom')\n")
    # Without a profile the run would enter learning mode and write rules.
    (tmp_path / ".py-sandboxes").write_text("py-sandbox=true\nos-sandbox=none\npython-import=*\n")

    result = subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", str(script)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    assert "boom" in result.stderr
    assert "<string>" not in result.stderr
