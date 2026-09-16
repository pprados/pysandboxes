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

The last section covers what the guards rest on rather than the guards themselves:
the program's output comes back, a profile that names its modules one by one still
starts, a failure says why, and stdout and stderr reach the caller apart from each
other. Each of the first three pins a defect that made every QEMU row here
exit 1 with an empty stderr -- read as "the VM does not come up", for as long as
nothing reported the cause. None of the three is specific to QEMU: a VM only made
them visible, by putting a console filter and a second interpreter in the way.
"""

import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from ._env import backend_of, os_sandbox_params, provider_skip_reason, row_profile_lines

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
    backend = backend_of(os_sandbox)
    profile.write_text(
        f"py-sandbox=true\nos-sandbox={backend}\n{row_profile_lines(os_sandbox)}{exposed}{profile_lines}"
    )
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
        timeout=_QEMU_TIMEOUT_SECONDS if backend == "qemu" else _TIMEOUT_SECONDS,
    )


def _skip_unavailable(os_sandbox: str) -> None:
    reason = provider_skip_reason(os_sandbox)
    if reason:
        pytest.skip(reason)


# --- guard_eval ---------------------------------------------------------------


@pytest.mark.parametrize("os_sandbox", os_sandbox_params())
def test_eval_is_refused_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """An application `eval()` is denied whatever confines the process."""
    _skip_unavailable(os_sandbox)
    done = _run(os_sandbox, "python-import=*\n", "print(eval('40 + 2'))\n", tmp_path)
    assert done.returncode != 0, done.stdout
    diagnostics = done.stderr
    assert "dynamic-code" in diagnostics, diagnostics


@pytest.mark.parametrize("os_sandbox", os_sandbox_params())
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


@pytest.mark.parametrize("os_sandbox", os_sandbox_params())
def test_os_system_is_refused_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """`os.system` is on the blacklist, and stays there under every backend."""
    _skip_unavailable(os_sandbox)
    done = _run(os_sandbox, "python-import=*\n", "import os\nos.system('true')\n", tmp_path)
    assert done.returncode != 0, done.stdout
    diagnostics = done.stderr
    assert "denied by the API guard" in diagnostics, diagnostics


@pytest.mark.parametrize("os_sandbox", os_sandbox_params())
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


@pytest.mark.parametrize("os_sandbox", os_sandbox_params())
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
    diagnostics = done.stderr
    assert f"'{_DENIED_MODULE}' is not allowed by a rule" in diagnostics, diagnostics


@pytest.mark.parametrize("os_sandbox", os_sandbox_params())
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


# --- what the guards rest on --------------------------------------------------


@pytest.mark.parametrize("os_sandbox", os_sandbox_params())
def test_program_output_reaches_the_caller_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """What the program prints comes back to whoever launched it.

    Every allow row above reads the program's own output to tell an accepted call
    from a broken start, so output that never arrives reports as a dead guard. It
    is also the product itself: a sandbox that swallows ``print()`` runs the code
    and loses the answer.

    QEMU lost it. The guest's stdout is a pipe, not the serial tty, so CPython
    block-buffers it, while the sentinels the host filters on are flushed to
    stderr -- the buffer reached the console after the closing sentinel and the
    filter dropped it. The guest interpreter now runs unbuffered.
    """
    _skip_unavailable(os_sandbox)
    done = _run(os_sandbox, "python-import=*\n", "print('MARKER-OUT', 40 + 2)\n", tmp_path)
    assert done.returncode == 0, done.stderr
    assert "MARKER-OUT 42" in done.stdout, done.stdout


@pytest.mark.parametrize("os_sandbox", os_sandbox_params())
def test_a_profile_naming_its_modules_starts_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """A profile without ``python-import=*`` still gets the interpreter going.

    This is the shape learning mode writes: it records what the run imported, so
    it never emits a wildcard. The harness defers imports of its own, and any one
    of those made after arming is charged to these rules -- the sandbox then dies
    on its own machinery, naming a stdlib module the program never asked for, and
    no profile the user can write would help.
    """
    _skip_unavailable(os_sandbox)
    done = _run(os_sandbox, "python-import=json\n", "print('STARTED')\n", tmp_path)
    assert done.returncode == 0, done.stderr
    assert "STARTED" in done.stdout, done.stdout


@pytest.mark.parametrize("os_sandbox", os_sandbox_params())
def test_a_failing_program_says_why_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """A program that raises exits non-zero *and* reports the cause.

    The exit code alone is what every deny row above already gets from a backend
    that failed to start. Silence is therefore the expensive failure: it makes a
    broken sandbox indistinguishable from a working guard, which is how the cause
    of the QEMU rows stayed unknown while the tests stayed red.
    """
    _skip_unavailable(os_sandbox)
    done = _run(os_sandbox, "python-import=*\n", "raise RuntimeError('MARKER-BOOM')\n", tmp_path)
    assert done.returncode != 0, done.stdout
    diagnostics = done.stderr
    assert "MARKER-BOOM" in diagnostics, diagnostics


@pytest.mark.parametrize("os_sandbox", os_sandbox_params())
def test_the_two_streams_stay_apart_under_every_backend(os_sandbox: str, tmp_path: Path) -> None:
    """What the program wrote to stdout comes back on stdout, and stderr on stderr.

    A process-based backend gets this for free. QEMU does not: ``-nographic``
    multiplexes the guest console onto one host stream, which used to hand the caller
    both outputs merged on stdout -- a program behaving differently for having been
    run in a VM. The guest now sends its stderr through the shared run dir instead.

    Neither stream is required to be empty: a backend is free to warn on stderr. The
    claim is that a marker never crosses over.
    """
    _skip_unavailable(os_sandbox)
    script = "import sys\nprint('MARKER-OUT')\nprint('MARKER-ERR', file=sys.stderr, flush=True)\n"
    done = _run(os_sandbox, "python-import=sys\n", script, tmp_path)
    assert done.returncode == 0, done.stderr
    assert "MARKER-OUT" in done.stdout, done.stdout
    assert "MARKER-ERR" in done.stderr, done.stderr
    assert "MARKER-ERR" not in done.stdout, done.stdout
    assert "MARKER-OUT" not in done.stderr, done.stderr
