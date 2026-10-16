# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The ``eval-*`` sub-language, enforced at run time through each backend.

``test_eval_integration`` proves the guard arms in a real process. These cases drive what the runtime helpers
of ``eval_runtime`` decide while an evaluated source runs: the budgets, the names and attributes it may use, the
imports it may make, and the doors that stay shut. Each case runs in its own ``python-sb`` process, as the
user's script would.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from ._env import backend_of, coverage_profile_lines, os_sandbox_params, row_profile_lines
from .test_guards_with_providers import _INTERPRETER_PATHS, _TIMEOUT_SECONDS, ROOT_DIR, _skip_unavailable

_ROWS = [row for row in os_sandbox_params() if not str(row.values[0]).startswith("qemu")]

_PRELUDE = """
from pysandboxes import EvalInterrupted

def attempt(label, function):
    try:
        print(label, "OK", function())
    except EvalInterrupted as error:
        print(label, "INTERRUPTED", error.reason)
    except BaseException as error:
        print(label, "REFUSED", type(error).__name__)

CLOSED = {"__builtins__": {}}
"""

# (id, eval-* rules, script body, the lines the run must print)
_CASES = [
    (
        "syntax-only-what-the-profile-names",
        "eval-syntax=arith\neval-namespace=closed\n",
        'attempt("sum", lambda: eval("6 * 7", CLOSED, {}))\nattempt("call", lambda: eval("abs(-1)", CLOSED, {}))\n',
        ["sum OK 42", "call REFUSED"],
    ),
    (
        "too-many-nodes",
        "eval-syntax=arith\neval-namespace=closed\neval-max-nodes=8\n",
        'attempt("small", lambda: eval("1 + 1", CLOSED, {}))\n'
        'attempt("large", lambda: eval(" + ".join(["1"] * 20), CLOSED, {}))\n',
        ["small OK 2", "large REFUSED"],
    ),
    (
        "too-deep",
        "eval-syntax=arith\neval-namespace=closed\neval-max-depth=4\n",
        'attempt("flat", lambda: eval("1 + 2", CLOSED, {}))\n'
        'attempt("nested", lambda: eval("-(-(-(-(-(-1)))))", CLOSED, {}))\n',
        ["flat OK 3", "nested REFUSED"],
    ),
    (
        "loop-budget",
        "eval-syntax=loop\neval-syntax=assign\neval-syntax=arith\neval-syntax=compare\n"
        "eval-namespace=closed\neval-max-iterations=1000\neval-timeout=10s\n",
        'attempt("short", lambda: exec("i = 0\\nwhile i < 10:\\n    i += 1", CLOSED, {}))\n'
        'attempt("long", lambda: exec("i = 0\\nwhile i < 10_000_000:\\n    i += 1", CLOSED, {}))\n',
        ["short OK None", "long INTERRUPTED"],
    ),
    (
        "comprehension-budget",
        "eval-syntax=comprehension\neval-call=range\neval-namespace=closed\neval-max-iterations=500\n",
        'attempt("short", lambda: len(eval("[i for i in range(50)]", CLOSED, {})))\n'
        'attempt("long", lambda: eval("[i for i in range(100_000)]", CLOSED, {}))\n',
        ["short OK 50", "long INTERRUPTED"],
    ),
    (
        "allocation-budget",
        "eval-syntax=arith\neval-namespace=closed\neval-max-alloc=1MB\n",
        'attempt("small", lambda: len(eval("\'x\' * 100", CLOSED, {})))\n'
        'attempt("huge", lambda: len(eval("\'x\' * 50_000_000", CLOSED, {})))\n',
        ["small OK 100", "huge REFUSED"],
    ),
    (
        "calls-only-by-name",
        "eval-syntax=arith\neval-call=len\neval-namespace=closed\n",
        'attempt("granted", lambda: eval("len((1, 2, 3))", CLOSED, {}))\n'
        'attempt("not granted", lambda: eval("abs(-1)", CLOSED, {}))\n',
        ["granted OK 3", "not granted REFUSED"],
    ),
    (
        "attributes-only-by-name",
        "eval-syntax=arith\neval-call=*\neval-attribute=upper\neval-namespace=closed\n",
        'attempt("granted", lambda: eval("\'ab\'.upper()", CLOSED, {}))\n'
        'attempt("not granted", lambda: eval("\'ab\'.lower()", CLOSED, {}))\n',
        ["granted OK AB", "not granted REFUSED"],
    ),
    (
        "frame-capture-stays-refused-even-with-every-attribute-allowed",
        "eval-syntax=comprehension\neval-syntax=arith\neval-call=*\neval-attribute=*\neval-namespace=closed\n",
        'attempt("frame", lambda: eval("(x for x in [1]).gi_frame", CLOSED, {}))\n',
        ["frame REFUSED"],
    ),
    (
        "imports-only-the-modules-named",
        "eval-syntax=import\neval-call=__import__\neval-import=math\neval-namespace=closed\n",
        'attempt("granted", lambda: exec("import math", CLOSED, {}))\n'
        'attempt("not granted", lambda: exec("import os", CLOSED, {}))\n',
        ["granted OK None", "not granted REFUSED"],
    ),
    (
        "call-depth-budget",
        "eval-syntax=func\neval-syntax=assign\neval-syntax=arith\neval-syntax=compare\neval-syntax=conditional\n"
        "eval-call=*\neval-namespace=closed\neval-max-call-depth=5\n",
        'SOURCE = "def down(n):\\n    return 0 if n == 0 else down(n - 1)\\nresult = down(%d)"\n'
        'attempt("shallow", lambda: exec(SOURCE % 3, dict(CLOSED), {}))\n'
        'attempt("deep", lambda: exec(SOURCE % 50, dict(CLOSED), {}))\n',
        ["shallow OK None", "deep INTERRUPTED"],
    ),
    (
        "the-caller-namespace-is-seen-only-in-caller-mode",
        "eval-syntax=arith\neval-namespace=caller\n",
        'secret = 41\nattempt("caller", lambda: eval("secret + 1"))\n',
        ["caller OK 42"],
    ),
    (
        "a-closed-namespace-hides-the-caller-variables",
        "eval-syntax=arith\neval-namespace=closed\n",
        'secret = 41\nattempt("closed", lambda: eval("secret + 1"))\n',
        ["closed REFUSED"],
    ),
]


def _run(os_sandbox: str, eval_rules: str, body: str, tmp_path: Path) -> "subprocess.CompletedProcess[str]":
    target = tmp_path / "script.py"
    target.write_text(_PRELUDE + textwrap.dedent(body))
    profile = tmp_path / "eval.profile"
    exposed = "".join(f"expose-ro={path}\n" for path in (str(tmp_path), *_INTERPRETER_PATHS))
    profile.write_text(
        f"py-sandbox=true\nos-sandbox={backend_of(os_sandbox)}\n{row_profile_lines(os_sandbox)}"
        f"python-import=*\n{exposed}{coverage_profile_lines()}{eval_rules}"
    )
    return subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={profile}", str(target)],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_SECONDS,
    )


@pytest.mark.parametrize("os_sandbox", _ROWS)
@pytest.mark.parametrize(("eval_rules", "body", "expected"), [case[1:] for case in _CASES], ids=[c[0] for c in _CASES])
def test_the_runtime_enforces_the_declared_sub_language(
    os_sandbox: str, eval_rules: str, body: str, expected: list[str], tmp_path: Path
) -> None:
    _skip_unavailable(os_sandbox)

    done = _run(os_sandbox, eval_rules, body, tmp_path)

    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    for line in expected:
        assert any(out.startswith(line) for out in lines), (line, done.stdout)
