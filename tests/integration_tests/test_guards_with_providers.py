# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The Python-layer guards must hold under every OS sandbox backend.

``test_usage_with_providers`` already covers three families per backend -- files,
sockets, environment variables -- by running ``tst_usage`` once per provider. This
file covers the three that scenario never exercises: dynamic code (``guard_eval``),
sensitive calls (``guard_api``) and imports (``guard_import``).

These guards live entirely in the Python layer, so the backend underneath is not
supposed to change their verdict. That is exactly the claim worth testing: the OS
backend is what rebuilds the interpreter's world -- namespaces, mounts, a fresh
process, in QEMU's case a whole VM -- and arming has to survive that. A guard that
is armed under ``subprocess`` and inert under ``qemu`` would deny nothing while
every existing test stayed green.

Each family is a deny/allow pair, the shape ``test_guard_api_arming`` uses. The
deny row proves the guard refuses; the allow row proves the refusal came from the
rule and not from a profile so narrow the interpreter never got going. Alone, a
deny row cannot tell a working guard from a broken startup -- both exit non-zero.

Profiles are written per test and carry no ``net=`` rule, unlike the shared
``py-sandbox-test.profile``: resolving a hostname at config load has nothing to do
with whether a guard is armed, and requiring it would skip this whole file on a
host without DNS.

Five backends were verified when this file was written -- subprocess, unshare,
firejail, landlock, bwrap. The QEMU rows were not: on a host with no ``/dev/kvm``
they exit 1 with an empty stderr, before any guard runs. The same profile and the
same script pass on the other five, so this is the VM failing to come up rather
than the guard, but the cause was not established. A red QEMU row here is not
necessarily your change.
"""

import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from ._env import ALL_OS_SANDBOX, provider_skip_reason

# Project root (parent of tests/), where the package and its venv live.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

# A backend that confines the filesystem hides the interpreter's own library tree unless
# it is named. Imports resolved *inside* the sandbox read that tree and guard_files has
# no stdlib exemption, so without these the child dies importing pysandboxes -- a failure
# that has nothing to do with the guard under test. The shared profile spells the same
# thing out; see its expose-ro= comments.
_INTERPRETER_PATHS: tuple[str, ...] = (
    str(ROOT_DIR),
    sysconfig.get_paths()["stdlib"],
    sysconfig.get_paths()["purelib"],
    sys.base_prefix,
)

# QEMU boots a VM before it runs anything; the others are a process away. The VM budget
# is deliberately generous: without KVM the guest runs under TCG emulation, where a boot
# that takes seconds on a bare-metal host can take minutes.
#
# This bounds the whole run, not the boot. pysandboxes gives the daemon
# TIMEOUT_FOR_START_DAEMON_QEMU (90s, a constant with no override) to answer, so a guest
# slower than that fails here whatever this value is; raising this only stops a slow but
# working boot from being cut off mid-flight.
_TIMEOUT_SECONDS = 600
_QEMU_TIMEOUT_SECONDS = 1800

# A stdlib module the interpreter does not need to reach user code, so denying it
# proves the guard rather than breaking startup. Pure Python and rarely imported by
# the framework, which keeps it out of sys.modules until the script asks for it.
#
# It also has to import nothing itself: `python-import` filters the top-level name of
# every import, so a module with dependencies would need each of them whitelisted too,
# and the allow row would be testing that transitive list rather than the guard.
# `colorsys` imports nothing at all.
_DENIED_MODULE = "colorsys"


def _run(
    os_sandbox: str,
    profile_lines: str,
    script: str,
    tmp_path: Path,
) -> "subprocess.CompletedProcess[str]":
    """Run ``script`` under ``python-sb`` with ``os_sandbox`` and the given rules."""
    target = tmp_path / "script.py"
    target.write_text(script)
    profile = tmp_path / "guard.profile"
    # The backend confines the filesystem, so the script pytest just wrote is invisible
    # to the child unless its directory is exposed, and so is the interpreter it runs on.
    exposed = "".join(f"expose-ro={path}\n" for path in (str(tmp_path), *_INTERPRETER_PATHS))
    profile.write_text(f"py-sandbox=true\nos-sandbox={os_sandbox}\n{exposed}{profile_lines}")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pysandboxes.python_sb",
            f"--pysandboxes-config={profile}",
            str(target),
        ],
        # From the project root, as test_usage_with_providers does: the package resolves
        # through the current directory, so running from tmp_path would silently test
        # whatever `pysandboxes` the environment installed rather than this checkout.
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=_QEMU_TIMEOUT_SECONDS if os_sandbox == "qemu" else _TIMEOUT_SECONDS,
    )


def _skip_unavailable(os_sandbox: str) -> None:
    reason = provider_skip_reason(os_sandbox)
    if reason:
        pytest.skip(reason)


# --- guard_eval ---------------------------------------------------------------


@pytest.mark.parametrize("os_sandbox", ALL_OS_SANDBOX)
def test_eval_is_refused_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """An application `eval()` is denied whatever confines the process."""
    _skip_unavailable(os_sandbox)
    done = _run(os_sandbox, "python-import=*\n", "print(eval('40 + 2'))\n", tmp_path)
    assert done.returncode != 0, done.stdout
    assert "dynamic-code" in done.stderr, done.stderr


@pytest.mark.parametrize("os_sandbox", ALL_OS_SANDBOX)
def test_eval_is_allowed_by_its_rule_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """The same call passes once the rule allows it -- so the refusal above was the guard."""
    _skip_unavailable(os_sandbox)
    done = _run(
        os_sandbox,
        "python-import=*\npython-api=ALLOW:dynamic-code\n",
        "print(eval('40 + 2'))\n",
        tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "42" in done.stdout, done.stdout


# --- guard_api ----------------------------------------------------------------


@pytest.mark.parametrize("os_sandbox", ALL_OS_SANDBOX)
def test_os_system_is_refused_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """`os.system` is on the blacklist, and stays there under every backend."""
    _skip_unavailable(os_sandbox)
    done = _run(os_sandbox, "python-import=*\n", "import os\nos.system('true')\n", tmp_path)
    assert done.returncode != 0, done.stdout
    assert "denied by the API guard" in done.stderr, done.stderr


@pytest.mark.parametrize("os_sandbox", ALL_OS_SANDBOX)
def test_os_system_is_allowed_by_its_rule_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """An explicit ALLOW resolves under every backend, so the deny row is not a broken startup.

    What is asserted is that the call reached the OS and returned a status -- not which
    status. The profile exposes no ``/bin``, so under a backend that builds its own
    mount namespace the shell reports 127; that is the command being absent, which says
    nothing about the guard. A refusal would raise instead of returning.
    """
    _skip_unavailable(os_sandbox)
    done = _run(
        os_sandbox,
        "python-import=*\npython-api=ALLOW:os.system,posix.system\n",
        "import os\n"
        "try:\n"
        "    print('CALLED', isinstance(os.system('true'), int))\n"
        "except BaseException as err:\n"
        "    print('REFUSED', type(err).__name__)\n",
        tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "CALLED True" in done.stdout, done.stdout


# --- guard_import -------------------------------------------------------------


@pytest.mark.parametrize("os_sandbox", ALL_OS_SANDBOX)
def test_an_unlisted_import_is_refused_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """`python-import` is a whitelist: a module no rule names cannot be imported.

    The assertion names the module, so a backend that fails to start -- also a
    non-zero exit -- does not read as a working guard.
    """
    _skip_unavailable(os_sandbox)
    done = _run(
        os_sandbox,
        "python-import=json\n",
        f"import {_DENIED_MODULE}\nprint('IMPORTED')\n",
        tmp_path,
    )
    assert done.returncode != 0, done.stdout
    assert "IMPORTED" not in done.stdout, done.stdout
    assert f"'{_DENIED_MODULE}' is not allowed by a rule" in done.stderr, done.stderr


@pytest.mark.parametrize("os_sandbox", ALL_OS_SANDBOX)
def test_a_listed_import_is_accepted_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """Naming the module in the whitelist lets it through, under the same narrow profile."""
    _skip_unavailable(os_sandbox)
    done = _run(
        os_sandbox,
        f"python-import=json,{_DENIED_MODULE}\n",
        f"import {_DENIED_MODULE}\nprint('IMPORTED', {_DENIED_MODULE}.hls_to_rgb(0.0, 0.5, 1.0))\n",
        tmp_path,
    )
    assert done.returncode == 0, done.stderr
    assert "IMPORTED (1.0, 0.0, 0.0)" in done.stdout, done.stdout
