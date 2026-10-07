# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The sandbox daemon's own imports are never charged to the user's python-import rules."""

import re
import subprocess
import sys
import sysconfig
import textwrap
from pathlib import Path

USERLIB = """
from pysandboxes import sandbox


@sandbox
def nothing() -> int:
    return 1


@sandbox
def import_module(name: str) -> str:
    __import__(name)
    return "imported"


@sandbox
def framework_names() -> list[str]:
    from pysandboxes import guard_import

    return sorted(guard_import._framework_names)
"""

# What the daemon may import for itself, and sandboxed code therefore without a rule:
# keep in step with the list in wiki/weaknesses.md.
FRAMEWORK_IMPORTS = frozenset("""
    __future__ _hashlib _hmac _multiprocessing _queue abc annotated_doc annotated_types annotationlib anyio array
    ast asyncio base64 binascii click codecs collections colorsys concurrent configparser contextlib contextvars
    copy copyreg dataclasses datetime decimal email enum errno fastapi fractions functools gettext h11 hashlib
    heapq hmac html http importlib inspect io ipaddress itertools json keyword locale logging math mimetypes
    multiprocessing operator os pathlib pickle platform pydantic pydantic_core pysandboxes queue random re
    secrets selectors shlex signal socket socketserver ssl starlette stat struct tempfile textwrap threading time
    traceback types typing typing_extensions typing_inspection urllib uuid uvicorn weakref zoneinfo
    """.split())

DRIVER = """
import sys
from pathlib import Path

from pysandboxes import sandbox_denials, sandboxes

import userlib

profile = Path(sys.argv[1])
extra = {"learn": str(profile)} if len(sys.argv) > 2 and sys.argv[2] == "learn" else {}
with sandboxes(sandboxes_config=profile, **extra):
    print("RESULT", userlib.nothing())
    print("FRAMEWORK", " ".join(userlib.framework_names()))
    if len(sys.argv) > 2 and sys.argv[2] != "learn":
        try:
            print("IMPORTED", userlib.import_module(sys.argv[2]))
        except Exception as e:
            print("DENIALS", sandbox_denials(e))
"""


def _run(tmp_path: Path, imports: str, *args: str) -> tuple["subprocess.CompletedProcess[str]", Path]:
    """Call userlib under a partial-mode sandbox whose profile allows `imports`."""
    (tmp_path / "userlib.py").write_text(USERLIB)
    (tmp_path / "driver.py").write_text(DRIVER)
    paths = sysconfig.get_paths()
    profile = tmp_path / ".py-sandboxes"
    profile.write_text(textwrap.dedent(f"""\
            py-sandbox=true
            os-sandbox=subprocess
            expose-rw={tmp_path}
            expose-ro={paths["stdlib"]}
            expose-ro={paths["purelib"]}
            expose-ro={Path(__file__).parents[2]}
            """) + (f"python-import={imports}\n" if imports else ""))
    done = subprocess.run(
        [sys.executable, "driver.py", str(profile), *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return done, profile


def test_a_profile_naming_only_the_application_serves_a_call(tmp_path: Path) -> None:
    done, _ = _run(tmp_path, "userlib")
    assert done.returncode == 0, done.stderr
    assert "RESULT 1" in done.stdout


def test_learning_charges_only_the_application_modules(tmp_path: Path) -> None:
    done, profile = _run(tmp_path, "", "learn")
    assert done.returncode == 0, done.stderr
    learned = re.findall(r"^python-import=(.+)$", profile.read_text(), re.MULTILINE)
    assert learned == ["userlib"]


def test_an_import_outside_the_rules_is_still_refused(tmp_path: Path) -> None:
    done, _ = _run(tmp_path, "userlib", "csv")
    assert done.returncode == 0, done.stderr
    assert "IMPORTED" not in done.stdout
    assert """DENIALS ["RuleModuleNotFoundError: Module named 'csv' is not allowed by a rule"]""" in done.stdout


def test_the_daemon_allows_itself_only_the_documented_modules(tmp_path: Path) -> None:
    done, _ = _run(tmp_path, "userlib")
    assert done.returncode == 0, done.stderr
    recorded = set(re.search(r"^FRAMEWORK (.*)$", done.stdout, re.MULTILINE)[1].split())  # type: ignore[index]
    assert "uvicorn" in recorded
    assert recorded <= FRAMEWORK_IMPORTS, f"undocumented: {sorted(recorded - FRAMEWORK_IMPORTS)}"
