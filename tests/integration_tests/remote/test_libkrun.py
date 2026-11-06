# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Integration tests for the libkrun OS sandbox provider."""

import json
import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path

import pytest

from pysandboxes.remote.libkrun_sse_daemon import LibkrunSSEDaemon
from pysandboxes.sandboxes_api import sandboxes

_ROOT = Path(__file__).resolve().parents[3]

_PROBE = """
import json, os

def outcome(path):
    try:
        with open(path) as handle:
            return "READ " + handle.read().strip()
    except OSError as error:
        return "DENIED " + type(error).__name__

def write_outcome(path):
    try:
        open(path, "w").close()
        return "ALLOWED"
    except OSError:
        return "DENIED"

status = open("/proc/self/status").read()
print(json.dumps({
    "hidden": outcome(os.environ["HIDDEN"]),
    "shown": outcome(os.environ["SHOWN"]),
    "ignored": outcome(os.environ["IGNORED"]),
    "write_root": write_outcome("/probe-write"),
    "uid": os.getuid(),
    "capabilities": status.split("CapEff:")[1].split()[0],
}))
"""


@pytest.fixture(autouse=True)
def _libkrun_available() -> None:
    reason = LibkrunSSEDaemon.unavailable_reason()
    if reason:
        pytest.skip(f"libkrun not available: {reason}")


@pytest.mark.asyncio
async def test_libkrun_basic() -> None:
    async with sandboxes(os_sandbox="libkrun"):
        pass


def _confined_probe(tmp_path: Path, *, expose_hidden: bool) -> dict:
    """Run the probe in the guest, with the Python guards off, so that only the provider can refuse."""
    # A directory of the user's home: no rule names it, and the guest's private /tmp does not hide it by accident.
    with tempfile.TemporaryDirectory(dir=Path.home(), prefix="libkrun-hidden-") as hidden_dir:
        hidden = Path(hidden_dir) / "secret.txt"
        hidden.write_text("secret")
        shown_dir = tmp_path / "shown"
        shown_dir.mkdir()
        shown = shown_dir / "shown.txt"
        shown.write_text("shown")
        ignored = shown_dir / "private.key"
        ignored.write_text("private")
        script = shown_dir / "probe.py"
        script.write_text(_PROBE)
        assert hidden.read_text() == "secret", "control: the host reads the file"
        profile = tmp_path / "files.profile"
        profile.write_text(
            "py-sandbox=false\nos-sandbox=libkrun\npython-import=*\nexpose-ro=.\nexpose-ro=/etc\n"
            f"expose-ro={sysconfig.get_paths()['stdlib']}\nexpose-ro={sys.base_prefix}/lib\n"
            f"expose-ro={shown_dir}\n"
            + (f"expose-ro={hidden_dir}\n" if expose_hidden else "")
            + f"ignore=private.key\nenv=HIDDEN={hidden}\nenv=SHOWN={shown}\nenv=IGNORED={ignored}\n"
        )
        done = subprocess.run(
            [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={profile}", str(script)],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_a_host_file_no_rule_names_is_not_in_the_guest(tmp_path: Path) -> None:
    seen = _confined_probe(tmp_path, expose_hidden=False)

    assert seen["hidden"] == "DENIED FileNotFoundError"
    assert seen["shown"] == "READ shown"


def test_the_same_file_exposed_by_a_rule_is_readable(tmp_path: Path) -> None:
    assert _confined_probe(tmp_path, expose_hidden=True)["hidden"] == "READ secret"


def test_the_guest_command_has_no_privilege_and_a_read_only_root(tmp_path: Path) -> None:
    seen = _confined_probe(tmp_path, expose_hidden=False)

    assert seen["uid"] == os.getuid()
    assert int(seen["capabilities"], 16) == 0
    assert seen["write_root"] == "DENIED"


def test_a_file_an_ignore_rule_names_is_masked_by_the_guest_root(tmp_path: Path) -> None:
    seen = _confined_probe(tmp_path, expose_hidden=False)

    # Masked, as with bwrap and gvisor: the read succeeds and returns nothing, never the content of the file.
    assert seen["ignored"] == "READ "
