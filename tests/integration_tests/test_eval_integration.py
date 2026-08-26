# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""End-to-end behaviour of the dynamic-code guard."""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest  # type: ignore[import-untyped]


def _run(profile: str, script: str, tmp_path: Path) -> "subprocess.CompletedProcess[str]":
    """Run `script` under python-sb with `profile`.

    The profile is passed with --pysandboxes-config and carries
    os-sandbox=subprocess, matching test_guard_api_arming. os-sandbox=subprocess
    leaves the Python layer inactive -- neither builtins.open nor
    builtins.eval is patched -- so a guard test written against it asserts
    nothing about the guard.
    """
    target = tmp_path / "script.py"
    target.write_text(textwrap.dedent(script))
    config = tmp_path / "eval.profile"
    # os-sandbox=subprocess confines the filesystem, so the script pytest just
    # wrote under /tmp is invisible to the child unless its directory is
    # exposed. Writable, because the learning round trip saves its profile back.
    config.write_text(textwrap.dedent(profile) + f"expose-rw={tmp_path}\n")
    return subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={config}", str(target)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_python_sb_still_starts_with_no_eval_key(tmp_path: Path) -> None:
    """Regression: the python_in_sb exec exemption holds."""
    done = _run(
        """
        py-sandbox=true
        os-sandbox=subprocess
        python-import=*
        """,
        "print(40 + 2)",
        tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "42" in done.stdout


def test_a_dataclass_still_works_with_no_eval_key(tmp_path: Path) -> None:
    """D5: the stdlib generates code with exec, after arming."""
    done = _run(
        """
        py-sandbox=true
        os-sandbox=subprocess
        python-import=*
        """,
        """
        import dataclasses

        @dataclasses.dataclass
        class Point:
            x: int = 0

        print(Point(x=42).x)
        """,
        tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "42" in done.stdout


def test_the_patched_eval_reaches_the_sandboxed_process(tmp_path: Path) -> None:
    """Separates "the patch never installed" from "the wrapper let it pass".

    Without this, a refusal that never arrives has two very different causes
    that look identical from the outside: builtins.eval still being the raw
    builtin, or the wrapper running and taking one of its passthrough
    branches. This names which.
    """
    done = _run(
        """
        py-sandbox=true
        os-sandbox=subprocess
        python-import=*
        """,
        """
        import builtins, sys
        print("PATCHED:", getattr(builtins.eval, "__pysandbox_eval__", False))
        print("OPEN:", getattr(builtins.open, "__pysandbox__", False))
        print("CALLER:", sys._getframe().f_code.co_filename)
        """,
        tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "PATCHED: True" in done.stdout, done.stdout


def test_an_application_eval_is_refused_with_no_eval_key(tmp_path: Path) -> None:
    done = _run(
        """
        py-sandbox=true
        os-sandbox=subprocess
        python-import=*
        """,
        "print(eval('40 + 2'))",
        tmp_path,
    )
    assert done.returncode != 0
    assert "dynamic-code" in done.stderr


def test_the_escape_hatch_restores_the_old_behaviour(tmp_path: Path) -> None:
    done = _run(
        """
        py-sandbox=true
        os-sandbox=subprocess
        python-import=*
        python-api=ALLOW:dynamic-code
        """,
        "print(eval('40 + 2'))",
        tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "42" in done.stdout


def test_a_declared_profile_guards_the_application_eval(tmp_path: Path) -> None:
    done = _run(
        """
        py-sandbox=true
        os-sandbox=subprocess
        python-import=*
        eval-namespace=closed
        eval-syntax=arith
        eval-timeout=2s
        """,
        """
        print(eval('40 + 2', {'__builtins__': {}}, {}))
        try:
            eval('[c for c in ().__class__.__base__.__subclasses__()]', {'__builtins__': {}}, {})
        except BaseException as err:
            print('REFUSED', type(err).__name__)
        """,
        tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "42" in done.stdout
    assert "REFUSED" in done.stdout


def test_a_timeout_is_recoverable_by_the_caller(tmp_path: Path) -> None:
    done = _run(
        """
        py-sandbox=true
        os-sandbox=subprocess
        python-import=*
        eval-namespace=closed
        eval-syntax=loop
        eval-max-iterations=1_000_000_000
        eval-timeout=1s
        """,
        """
        from pysandboxes import EvalInterrupted
        try:
            exec('while True:\\n    pass', {'__builtins__': {}}, {})
        except EvalInterrupted as err:
            print('INTERRUPTED', err.reason)
        print('ALIVE')
        """,
        tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "INTERRUPTED" in done.stdout
    assert "ALIVE" in done.stdout


def test_the_learning_round_trip_produces_a_replayable_profile(tmp_path: Path) -> None:
    """learn -> write -> replay passes."""
    profile = tmp_path / ".py-sandboxes"
    profile.write_text(textwrap.dedent(f"""
            py-sandbox=true
            os-sandbox=subprocess
            python-import=*
            learn={profile}
            """))
    script = tmp_path / "script.py"
    script.write_text("print(eval('sum([i * 2 for i in range(3)])'))")
    first = subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert first.returncode == 0, first.stderr
    learned = profile.read_text()
    assert "eval-syntax=" in learned
    # Asserted on the emitted eval- lines rather than on the span between the
    # <learning_guard_eval> markers: those markers come from the template, and
    # this profile was hand-written, so the span would be the whole file and
    # the `*` of python-import= would fail an assertion about eval rules.
    emitted = [line for line in learned.splitlines() if line.startswith("eval-")]
    assert emitted
    assert all("*" not in line for line in emitted), emitted
    profile.write_text(learned.replace(f"learn={profile}", ""))
    second = subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert second.returncode == 0, second.stderr
    assert "6" in second.stdout


@pytest.mark.parametrize("flag", ["-c"])
def test_python_sb_dash_c_still_runs(flag: str, tmp_path: Path) -> None:
    (tmp_path / ".py-sandboxes").write_text("py-sandbox=true\nos-sandbox=subprocess\npython-import=*\n")
    done = subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", flag, "print(40 + 2)"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
    assert "42" in done.stdout
