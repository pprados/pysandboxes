# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""socket.socket is a subclass; the guard stops at the subclass.

Unlike posix, this is not one object under two names: `socket.socket is
_socket.socket` is False. socket.socket is a Python subclass of the C
_socket.socket, and it does not redefine connect -- so patching the subclass
attribute leaves the base class method untouched, and an instance built from
`_socket.socket(...)` never consults the guard.

The C type is immutable, so the base class method cannot be patched. What can
be replaced is the name the module publishes, which is what an attacker has to
go through: `import _socket; _socket.socket(...)`. The base class stays
reachable via socket.socket.__mro__[1]; this closes the named route.
"""

import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes._os_sandbox import unsupported_platform_reason
from pysandboxes.guard_socket import patch_rules

# The end-to-end probes run under os-sandbox=subprocess, the provider that keeps the
# Python guards armed; `none` disarms them, so it cannot stand in where subprocess is missing.
_needs_subprocess = pytest.mark.skipif(
    unsupported_platform_reason("subprocess") is not None,
    reason=unsupported_platform_reason("subprocess") or "",
)


def test_the_c_class_name_hands_back_a_guarded_subclass() -> None:
    """The rule replaces the published name, not a method of the C type."""
    import _socket

    rules = patch_rules(learn=False)
    assert "_socket.socket" in rules, "the C module still publishes the unguarded class"

    guarded = rules["_socket.socket"](_socket.socket)
    assert issubclass(guarded, _socket.socket)
    assert guarded.connect is not _socket.socket.connect

    # guard_eval grades a callable by __module__. A subclass reporting
    # pysandboxes.guard_socket falls out of STRONG_MODULES and gets handed to
    # eval contexts that refuse the real class.
    assert guarded.__module__ == _socket.socket.__module__


def test_the_subclass_keeps_the_one_call_site_socket_py_uses() -> None:
    """socket.py calls `_socket.socket.__init__(self, ...)` unbound.

    Handing back socket.socket made that call its own and recursed. The
    forwarding __init__ is what keeps socket.socket constructible.
    """
    import _socket

    guarded = patch_rules(learn=False)["_socket.socket"](_socket.socket)
    assert "__init__" in guarded.__dict__
    # Constructing it is the assertion: the recursion this guards against was an
    # infinite one, so a socket that comes back at all is the proof.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        assert isinstance(probe, socket.socket)


@_needs_subprocess
def test_connect_through_the_c_class_is_refused(tmp_path: Path) -> None:
    """The point of the change, end to end under python-sb.

    Run out of process: the patch is posted by the import hook, so this needs a
    real interpreter start rather than a table inspection. The target is
    TEST-NET-1, outside the single allowed destination -- a GUARD proves the
    guard decided, any other outcome proves it was never asked.
    """
    work = tmp_path / "work"
    work.mkdir()
    (work / ".py-sandboxes").write_text(
        "py-sandbox=true\n"
        "os-sandbox=subprocess\n"
        "python-import=*\n"
        f"expose-rw={work}\n"
        f"expose-ro={Path.cwd()}\n"
        "net=ALLOW|TCP|127.0.0.1|9999|OUT\n"
    )
    (work / "probe.py").write_text(
        "import _socket\n"
        "import socket\n"
        "from pysandboxes.e import SandBoxError\n"
        "try:\n"
        "    sock = _socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "    sock.settimeout(0.25)\n"
        "    sock.connect(('192.0.2.1', 80))\n"
        "    print('ALLOWED')\n"
        "except SandBoxError:\n"
        "    print('GUARD')\n"
        "except BaseException as exc:\n"
        "    print('OTHER', type(exc).__name__)\n"
    )

    result = subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", "probe.py"],
        capture_output=True,
        text=True,
        cwd=work,
        env={**os.environ, "TMPDIR": str(work)},
    )

    assert "GUARD" in result.stdout, result.stdout + result.stderr


def test_every_guarded_resolution_call_has_its_c_twin() -> None:
    """socket.py does `from _socket import *`; the socket name is an alias.

    `socket.gethostbyname is _socket.gethostbyname` is one object under two
    names, the posix relationship. getaddrinfo is the other shape: socket.py
    redefines it in Python, so the raw C one is a separate, unguarded function
    rather than an alias. Either way the C name needs the same wrapper.
    """
    import _socket

    rules = patch_rules(learn=False)
    plain = [key for key in rules if key.startswith("socket.") and "." not in key[len("socket.") :]]

    for key in plain:
        name = key[len("socket.") :]
        if not hasattr(_socket, name):
            continue
        assert f"_socket.{name}" in rules, f"{key} is reachable unguarded as _socket.{name}"
        assert rules[f"_socket.{name}"] is rules[key]


@_needs_subprocess
def test_resolution_through_the_c_module_behaves_like_the_guarded_name(tmp_path: Path) -> None:
    """End to end: the C name must not be a softer path than the socket one.

    Asserting GUARD outright would only pass where DNS resolves; with no
    resolver the call dies of gaierror before the guard is consulted, which
    says nothing either way. What holds in both environments is that the two
    names produce the same outcome -- a difference is the bypass.

    Stated plainly: on a machine without DNS both names die of gaierror, so
    this passes with or without the twin rule. It is the table test above that
    catches a missing twin here; this one catches a divergence where the
    resolver answers.
    """
    work = tmp_path / "work"
    work.mkdir()
    (work / ".py-sandboxes").write_text(
        "py-sandbox=true\n"
        "os-sandbox=subprocess\n"
        "python-import=*\n"
        f"expose-rw={work}\n"
        f"expose-ro={Path.cwd()}\n"
        "net=ALLOW|TCP|127.0.0.1|9999|OUT\n"
    )
    (work / "probe.py").write_text(
        "import socket\n"
        "import _socket\n"
        "from pysandboxes.e import SandBoxError\n"
        "def outcome(call):\n"
        "    try:\n"
        "        call()\n"
        "        return 'ALLOWED'\n"
        "    except SandBoxError:\n"
        "        return 'GUARD'\n"
        "    except BaseException as exc:\n"
        "        return 'OTHER ' + type(exc).__name__\n"
        'for name, args in (("gethostbyname", ("example.com",)),\n'
        '                   ("getaddrinfo", ("example.com", 80))):\n'
        "    guarded = outcome(lambda: getattr(socket, name)(*args))\n"
        "    raw = outcome(lambda: getattr(_socket, name)(*args))\n"
        "    print(name, guarded, '|', raw)\n"
    )

    result = subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", "probe.py"],
        capture_output=True,
        text=True,
        cwd=work,
        env={**os.environ, "TMPDIR": str(work)},
    )

    lines = [line for line in result.stdout.splitlines() if " | " in line]
    assert len(lines) == 2, result.stdout + result.stderr
    for line in lines:
        name, rest = line.split(" ", 1)
        guarded, raw = (part.strip() for part in rest.split("|"))
        assert guarded == raw, f"{name}: socket gives {guarded!r}, _socket gives {raw!r}"
