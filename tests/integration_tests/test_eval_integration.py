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
    os-sandbox=subprocess, matching test_guard_api_arming. What arms the Python
    layer is py-sandbox=true, not the OS backend: under
    os-sandbox=subprocess both builtins.eval and io.open are patched, which
    test_the_patched_eval_reaches_the_sandboxed_process asserts. So a guard test
    written against this profile does exercise the guard.

    A fresh process rather than an in-process arming, because the unit tests
    reach the guard by another door: they call guarded_eval() directly, and
    activate_guard() only installs the profiles. Nothing there replaces
    builtins.eval. Only a real arming patches the builtin, and it patches it
    for the whole process -- under pytest that would outlive the test. So what
    is asserted here is what only a process can show: the patch being
    installed at startup, the exit code, the refusal on stderr, a learned
    profile written out and replayed by a second process.
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


def test_a_sandbox_decorated_function_is_guarded_when_it_evals(tmp_path: Path) -> None:
    """The `@sandbox` annotation is how an agent tool is written; the guard holds inside it.

    The samples all take that shape: a tool the model calls evaluates an
    expression the model produced. Asserting the guard only on a bare `eval()`
    in the script body says nothing about the decorated path, where the call
    goes through the `@sandbox` wrapper before reaching the patched builtin.

    `subprocess` is imported first so Popen is loaded, as it is in a real
    process: what refuses the escape then has to be the eval layer, not a class
    that happens to be absent from the subclass tree.
    """
    done = _run(
        """
        py-sandbox=true
        os-sandbox=subprocess
        python-import=*
        eval-namespace=closed
        eval-syntax=arith, compare
        eval-timeout=2s
        """,
        """
        import subprocess

        from pysandboxes import sandbox, sandbox_denials

        ESCAPE = (
            "[c for c in ().__class__.__base__.__subclasses__() "
            "if c.__name__=='Popen'][0](['/bin/echo','pwned'])"
        )

        @sandbox
        def evaluate(expression: str) -> float:
            return float(eval(expression, {'__builtins__': {}}, {}))

        print('SANE', evaluate('2*(3+4)'))
        try:
            evaluate(ESCAPE)
            print('ESCAPED')
        except BaseException as err:
            print('REFUSED', type(err).__name__, sandbox_denials(err))
        """,
        tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "SANE 14.0" in done.stdout, done.stdout
    assert "REFUSED EvalSyntaxRejected" in done.stdout, done.stdout
    assert "eval-syntax=comprehension" in done.stdout, done.stdout


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
