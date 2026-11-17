# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Regression guard: a real `python -m pysandboxes.python_sb -m <module>` launch.

Commit `02723db7` broke every `-m` launch under every OS provider (the entry module's own
`.pyc` read, through `runpy.run_module` -> `compile`/`marshal.loads`, was judged as the
application's own call site and denied with no `python-api=ALLOW:dynamic-code` grant);
`780e645b` fixed it. Neither commit's own tests ever launched a real child process: the
fix is pinned with synthetic frame chains in
`tests/unit_tests/guard/test_guard_eval_ambient_gateways.py`, run inside this process. The
regression itself reached `develop` and was only caught by a manual run of the cross-OS
suite on a Windows VM -- not by `make unit-tests`, which every push runs
(`.github/workflows/test.yml`).

This test closes that gap the cheapest way that still launches a real separate process:
`os-sandbox=subprocess` needs no kernel feature, no extra binary, and no network, so it
belongs in the unit tier rather than the integration suite's provider matrix. The tiny
module is the stdlib's own `this`: a real, non-frozen `.py` file guaranteed to be on the
sandboxed child's `sys.path` without adding the test's own temporary directory to it
(the daemon strips the child's environment, including `PYTHONPATH`, before launch).
"""

import subprocess
import sys
from pathlib import Path


def test_a_real_minus_m_launch_under_subprocess_starts_and_prints(tmp_path: Path) -> None:
    """No `eval-*` rule and no `python-api=ALLOW:dynamic-code` grant: the only thing that
    lets the module's own bytecode load is the framework's `-m` dispatch staying ambient.
    """
    (tmp_path / ".py-sandboxes").write_text("py-sandbox=true\nos-sandbox=subprocess\npython-import=this\n")

    result = subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", "-m", "this"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=60,
    )

    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    assert "The Zen of Python" in result.stdout
