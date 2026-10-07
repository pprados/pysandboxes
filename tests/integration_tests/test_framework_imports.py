# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The sandbox daemon's own imports are never charged to the user's rules, and never granted to the user's code."""

import re
import subprocess
import sys
import sysconfig
import textwrap
from pathlib import Path

import pytest

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
def import_json() -> str:
    import json

    return json.__name__


@sandbox
def import_json_with_forged_globals() -> str:
    return __import__("json", {"__name__": "uvicorn"}).__name__


@sandbox
def import_json_through_importlib() -> str:
    import importlib

    return importlib.import_module("json").__name__


@sandbox
def import_json_through_a_helper() -> str:
    import helper

    return helper.NAME


@sandbox
async def import_json_async() -> str:
    import json

    return json.__name__


@sandbox
def framework_names() -> list[str]:
    from pysandboxes import guard_import

    return sorted(guard_import._framework_names)
"""

HELPER = """
import json

NAME = json.__name__
"""

# What the daemon may import for itself: keep in step with the list in wiki/weaknesses.md.
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
import asyncio
import inspect
import sys
from pathlib import Path

from pysandboxes import sandbox_denials, sandboxes

import userlib

profile, mode, calls = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
extra = {"learn": str(profile)} if mode == "learn" else {}
with sandboxes(sandboxes_config=profile, **extra):
    print("RESULT", userlib.nothing())
    print("FRAMEWORK", " ".join(userlib.framework_names()))
    for call in calls:
        name, _, arg = call.partition("=")
        try:
            result = getattr(userlib, name)(*([arg] if arg else []))
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            print("CALL", call, "OK", result)
        except Exception as e:
            print("CALL", call, "DENIALS", sandbox_denials(e))
"""


def _run(tmp_path: Path, imports: str, mode: str, *calls: str) -> tuple["subprocess.CompletedProcess[str]", Path]:
    """Call userlib under a partial-mode sandbox whose profile allows `imports`."""
    (tmp_path / "userlib.py").write_text(USERLIB)
    (tmp_path / "helper.py").write_text(HELPER)
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
        [sys.executable, "driver.py", str(profile), mode, *calls],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return done, profile


def _outcome(done: "subprocess.CompletedProcess[str]", call: str) -> str:
    match = re.search(rf"^CALL {re.escape(call)} (.*)$", done.stdout, re.MULTILINE)
    assert match, done.stdout + done.stderr
    return match[1]


def test_a_profile_naming_only_the_application_serves_a_call(tmp_path: Path) -> None:
    done, _ = _run(tmp_path, "userlib", "strict")
    assert done.returncode == 0, done.stderr
    assert "RESULT 1" in done.stdout


def test_learning_charges_only_the_application_modules(tmp_path: Path) -> None:
    done, profile = _run(tmp_path, "", "learn")
    assert done.returncode == 0, done.stderr
    learned = re.findall(r"^python-import=(.+)$", profile.read_text(), re.MULTILINE)
    assert learned == ["userlib"]


def test_an_import_outside_the_rules_is_still_refused(tmp_path: Path) -> None:
    done, _ = _run(tmp_path, "userlib", "strict", "import_module=csv")
    assert done.returncode == 0, done.stderr
    assert _outcome(done, "import_module=csv") == (
        """DENIALS ["RuleModuleNotFoundError: Module named 'csv' is not allowed by a rule"]"""
    )


@pytest.mark.parametrize(
    "call",
    [
        "import_json",
        "import_json_with_forged_globals",
        "import_json_through_importlib",
        "import_json_through_a_helper",
        "import_json_async",
    ],
)
def test_a_module_the_daemon_loaded_is_still_refused_to_the_application(tmp_path: Path, call: str) -> None:
    done, _ = _run(tmp_path, "userlib, importlib, helper", "strict", call)
    assert done.returncode == 0, done.stderr
    assert (
        _outcome(done, call) == """DENIALS ["RuleModuleNotFoundError: Module named 'json' is not allowed by a rule"]"""
    )


def test_a_module_the_daemon_loaded_is_granted_by_a_rule(tmp_path: Path) -> None:
    done, _ = _run(tmp_path, "userlib, json", "strict", "import_json")
    assert done.returncode == 0, done.stderr
    assert _outcome(done, "import_json") == "OK json"


def test_learning_records_a_module_the_daemon_loaded(tmp_path: Path) -> None:
    done, profile = _run(tmp_path, "", "learn", "import_json")
    assert done.returncode == 0, done.stderr
    learned = re.findall(r"^python-import=(.+)$", profile.read_text(), re.MULTILINE)
    assert sorted(", ".join(learned).split(", ")) == ["json", "userlib"]


def test_the_daemon_allows_itself_only_the_documented_modules(tmp_path: Path) -> None:
    done, _ = _run(tmp_path, "userlib", "strict")
    assert done.returncode == 0, done.stderr
    recorded = set(re.search(r"^FRAMEWORK (.*)$", done.stdout, re.MULTILINE)[1].split())  # type: ignore[index]
    assert "uvicorn" in recorded
    assert recorded <= FRAMEWORK_IMPORTS, f"undocumented: {sorted(recorded - FRAMEWORK_IMPORTS)}"
