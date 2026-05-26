# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""``python-sb`` must honour ``TMPDIR`` for its host-side run directory.

That directory carries the configuration pipe passed to the sandboxed
child, so it must stay under whatever ``tempfile`` resolves to, not be
forced under ``/tmp``: on a host where ``/tmp`` is read-only and
``TMPDIR`` points elsewhere (a hardened container, a sandboxed CI
runner), forcing ``/tmp`` makes every invocation fail before running
any user code.
"""

import glob
import os
import subprocess
import sys
from pathlib import Path


def test_run_dir_follows_tmpdir(tmp_path: Path) -> None:
    profile = tmp_path / "tmpdir.profile"
    profile.write_text(
        "py-sandbox=true\nos-sandbox=subprocess\npython-import=*\n",
    )
    custom_tmp = tmp_path / "custom-tmpdir"
    custom_tmp.mkdir()
    before = set(glob.glob("/tmp/pysandboxes-sb-*"))

    env = {**os.environ, "TMPDIR": str(custom_tmp)}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pysandboxes.python_sb",
            f"--pysandboxes-config={profile}",
            "-c",
            "print(1)",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr
    # The run directory is removed on exit, so its transient location
    # cannot be asserted directly; this only proves /tmp was untouched.
    after = set(glob.glob("/tmp/pysandboxes-sb-*"))
    assert after == before
