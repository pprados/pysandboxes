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

from pysandboxes.guard_socket import patch_rules


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
    assert socket.socket(socket.AF_INET, socket.SOCK_STREAM).close() is None


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
