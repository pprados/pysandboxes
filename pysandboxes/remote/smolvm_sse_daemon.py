# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""smolvm provider: the sandboxed code runs in a libkrun microVM, with its own kernel, started by ``smolvm``.

The guest is an OCI image holding Python and pysandboxes. The package of the host is shared read-only and wins over
the image's, unless it sits where smolvm refuses to share (``/usr``, an installed package): the guest then runs the
copy in its image, which ``make build-smolvm-guest`` installs from the same wheel. The image runs the
Python of the host: the init script refuses another version.

The guest receives a few shares of the host and an init script that binds exactly what the rules expose (see
``smolvm_root``). The channel is a Unix socket the guest listens on and ``--expose-socket`` makes reachable on the
host. The config never touches the disk: it goes from the host FIFO to the standard input of the guest. The network
is off unless a rule opens it, and then filtered by the host side of smolvm.
"""

import logging
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from ..all_rules import AllRules
from ..e import SandBoxError
from ..guard_files import FSExposeRule
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg
from ..override_compat import override
from ..sb_types import Args, ConfigLine, ConfigLines, Envs
from ..tools import Environ
from .client_subprocess_sse_daemon import BaseSubProcessDaemon
from .smolvm_root import exposures, init_script, is_refused_by_smolvm, mask_targets, volumes
from .smolvm_rules import network_args
from .tools import which_command

logger = logging.getLogger(__name__)

_KVM_DEVICE = Path("/dev/kvm")
_IMAGE_ENV = "PYSANDBOXES_SMOLVM_IMAGE"
_PACKAGE_DIR = Path(__file__).resolve().parent.parent
_GUEST_SOCKET = "/tmp/pysb.sock"
_GUEST_PYTHON = "/usr/local/bin/python"
_HOST_PATH = "/usr/local/bin:/usr/bin:/bin"
# libkrun gives a micro-VM a handful of virtio-fs devices: 8 without a network, fewer with one.
_MAX_SHARES = 6
# Hands the guest its config, then the standard input of the caller, and dies with the launcher it was started by.
_RELAY = """\
import ctypes, os, signal, sys
ctypes.CDLL(None).prctl(1, signal.SIGKILL)
fifo, out, parent = sys.argv[1], sys.argv[2], int(sys.argv[3])
if os.getppid() != parent:
    sys.exit(0)
target = os.open(out, os.O_WRONLY)
def copy(source):
    while chunk := os.read(source, 65536):
        view = memoryview(chunk)
        while view:
            view = view[os.write(target, view):]
try:
    config = os.open(fifo, os.O_RDONLY)
    copy(config)
    copy(0)
except BrokenPipeError:
    pass
"""
# smolvm has no seccomp or landlock switch: the guest is hardened by dropping every capability, as the host user.
_PROFILE_KEYS = frozenset({"image", "python", "cpus", "mem"})


class SmolvmSSEDaemon(BaseSubProcessDaemon):
    """Runs the sandbox daemon in a smolvm microVM, reached through a Unix socket."""

    __slots__ = ()
    supports_unix_endpoint = True
    endpoint_handed_down = False

    @classmethod
    @override
    def unavailable_reason(cls) -> str | None:
        """Return why smolvm cannot run here, or None.

        post: __return__ is None or len(__return__) > 0
        """
        if which_command("smolvm") is None:
            return "smolvm not found, required for the smolvm provider"
        if sys.platform == "linux" and not os.access(_KVM_DEVICE, os.R_OK | os.W_OK):
            return f"{_KVM_DEVICE} is not accessible, smolvm needs KVM (in a container: --device /dev/kvm)"
        return None

    @override
    def parse_rules(
        self,
        rules: ConfigLines,
        errors: list[ErrorMsg],
    ) -> tuple[ImmutableDict[str, Any], ConfigLines]:
        """Split the ``smolvm.*`` keys from the other lines, which are passed through.

        post: len(__return__[1]) + len(__return__[0]) <= len(rules)
        """
        params: dict[str, str] = {}
        other: ConfigLines = []
        for rule in rules:
            if rule.rule.startswith("smolvm."):
                key, _, value = rule.rule[len("smolvm.") :].partition("=")
                params[key] = value
            else:
                other.append(rule)
        return ImmutableDict(params), other

    @override
    def update_rules_and_activate(self, *, all_rules: AllRules, envs: Envs) -> AllRules:
        """Let the Python layer read what the guest runs on and bind its channel, which the rules cannot name.

        The guest is confined from outside, so this adds, ahead of the user's rules, read access to the interpreter
        of the image and to the package, and write access to the channel socket alone. The rules name the host's
        interpreter, not the image's.
        """
        implicit = tuple(
            FSExposeRule(path, write, ConfigLine("<implicit smolvm guest>", Path(__file__), 0))
            for path, write in (
                (f"{Path(_GUEST_PYTHON).parent.parent}/lib/", False),
                (f"{_PACKAGE_DIR}/", False),
                (_GUEST_SOCKET, True),
            )
        )
        return all_rules._replace(file_rules=(*implicit, *all_rules.file_rules))

    @override
    def _guest_endpoint(self) -> str:
        if self.endpoint is None:
            raise SandBoxError("the smolvm provider needs a Unix endpoint: remote-endpoint=tcp is not supported")
        return f"unix://{_GUEST_SOCKET}"

    @staticmethod
    def _image(all_rules: AllRules) -> str:
        """The image of the guest: the ``smolvm.image`` key, else ``PYSANDBOXES_SMOLVM_IMAGE``."""
        image = str(all_rules.os_sandbox_params.get("image", "")) or os.environ.get(_IMAGE_ENV, "")
        if not image:
            raise SandBoxError(
                f"smolvm needs a guest image: set smolvm.image or {_IMAGE_ENV} (make build-image-smolvm)"
            )
        return image

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Return the command that hands the config to the guest through its standard input, then starts it.

        The guest cannot open the host FIFO the config travels through, and a file would stay on the disk for anyone
        to alter: the launcher gives the FIFO to ``smolvm`` as its standard input, which the guest reads as
        ``/dev/stdin``. What the caller appends to the command line, minus the pipe, is the guest's: the user's
        arguments of ``python-sb``.
        """
        smolvm = which_command("smolvm")
        if smolvm is None:
            raise SandBoxError("smolvm not found, required for the smolvm provider")
        inner_cmd, _ = super().subprocess_cmd(all_rules, envs, pipe_path, temp=temp)
        params = all_rules.os_sandbox_params
        if unknown := sorted(set(params.keys()) - _PROFILE_KEYS):
            raise SandBoxError(
                f"smolvm does not know {', '.join('smolvm.' + key for key in unknown)}; "
                f"it takes {', '.join('smolvm.' + key for key in sorted(_PROFILE_KEYS))}"
            )
        shared_package = not is_refused_by_smolvm(str(_PACKAGE_DIR))
        ro, rw = exposures(all_rules, extra_ro=[str(_PACKAGE_DIR)] if shared_package else [])
        share_flags = volumes(ro, rw)
        if len(share_flags) // 2 > _MAX_SHARES:
            raise SandBoxError(
                f"the rules need {len(share_flags) // 2} shares of the host and a smolvm guest takes {_MAX_SHARES}: "
                "fewer top directories, or fewer writable directories"
            )
        cwd = os.getcwd()
        guest_env = {key: str(value) for key, value in all_rules.envs.items()}
        if shared_package:
            guest_env["PYTHONPATH"] = str(_PACKAGE_DIR.parent)
        guest_python = str(params.get("python", "")) or _GUEST_PYTHON
        guest_script = init_script(
            ro=ro,
            rw=rw,
            masks=mask_targets(all_rules, cwd, [*ro, *rw]),
            cwd=cwd,
            uid=os.getuid(),
            gid=os.getgid(),
            env=guest_env,
            command=[guest_python, *inner_cmd[1:]],
            python_version=(sys.version_info.major, sys.version_info.minor),
        )
        socket = ["--expose-socket", f"{_GUEST_SOCKET}:{self.endpoint.path}"] if self.endpoint else []
        cmd = [
            str(smolvm),
            "machine",
            "run",
            "-i",
            "--image",
            self._image(all_rules),
            *(["--cpus", str(params["cpus"])] if params.get("cpus") else []),
            *(["--mem", str(params["mem"])] if params.get("mem") else []),
            *network_args(all_rules),
            *share_flags,
            *socket,
            "--",
            "/bin/sh",
            "-c",
            guest_script,
            "smolvm-guest",
        ]
        q = shlex.quote
        script = "\n".join(
            [
                "umask 077",
                'fifo=""; relay=0; n=$#',
                'while [ "$n" -gt 0 ]; do',
                "  a=$1; shift; n=$((n-1))",
                '  if [ "$a" = "--_named-pipe" ]; then fifo=$1; shift; n=$((n-1)); else set -- "$@" "$a"; fi',
                '  if [ "$a" = "--_python-sb" ]; then relay=1; fi',
                "done",
                'if [ "$relay" = 1 ]; then',
                "  exec 3<&0",
                '  d=$(mktemp -d) && mkfifo "$d/in" || exit 1',
                f'  {q(sys.executable)} -I -c {q(_RELAY)} "$fifo" "$d/in" $$ <&3 &',
                '  exec 4< "$d/in"; rm -rf "$d"',
                "  exec 0<&4 3<&- 4<&-",
                "else",
                '  exec 0< "$fifo"',
                "fi",
                "exec " + " ".join(q(arg) for arg in cmd) + ' "$@" --_config-on-stdin',
            ]
        )
        host_env = {"PATH": _HOST_PATH, "HOME": os.environ.get("HOME", "/")}
        host_env.update({key: value for key, value in os.environ.items() if key.startswith("SMOLVM")})
        return ["sh", "-c", script, "smolvm-launcher"], host_env
