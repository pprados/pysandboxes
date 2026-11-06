# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""smolvm provider: the sandboxed code runs in a libkrun microVM, with its own kernel, started by ``smolvm``.

The guest is an OCI image holding Python and the dependencies of pysandboxes; the package itself is mounted
read-only from the host. The channel is a Unix socket the guest listens on and ``--expose-socket`` makes reachable
on the host: the guest needs no network for it. The network is off unless a rule opens it, and then filtered by the
host side of smolvm.
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
from .smolvm_rules import network_args, volume_args
from .tools import which_command

logger = logging.getLogger(__name__)

_KVM_DEVICE = Path("/dev/kvm")
_IMAGE_ENV = "PYSANDBOXES_SMOLVM_IMAGE"
_GUEST_CONFIG_DIR = "/pysb"
_PACKAGE_DIR = Path(__file__).resolve().parent.parent
_GUEST_SOCKET = "/tmp/pysb.sock"
_GUEST_PYTHON = "/usr/local/bin/python"
_HOST_PATH = "/usr/local/bin:/usr/bin:/bin"
# smolvm has no seccomp or landlock switch: the guest is hardened by dropping capabilities (``--unprivileged``).
# ``--user`` is not offered, as a guest user cannot write to the host directories mounted read-write.
_PROFILE_KEYS = frozenset({"image", "python", "cpus", "mem", "unprivileged"})


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
                (f"{sys.base_prefix.rstrip('/')}/lib/", False),
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
        """Return the command that relays the config to the guest, then starts it.

        The guest cannot open the host FIFO the config travels through: the launcher copies it to a file of a
        directory mounted read-only, which holds nothing else. What the caller appends to the command line, minus the
        pipe, is the guest's: the user's arguments of ``python-sb``.
        """
        smolvm = which_command("smolvm")
        if smolvm is None:
            raise SandBoxError("smolvm not found, required for the smolvm provider")
        inner_cmd, _ = super().subprocess_cmd(all_rules, envs, pipe_path, temp=temp)
        guest_dir = temp / "smolvm-guest"
        guest_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        params = all_rules.os_sandbox_params
        if unknown := sorted(set(params.keys()) - _PROFILE_KEYS):
            raise SandBoxError(
                f"smolvm does not know {', '.join('smolvm.' + key for key in unknown)}; "
                f"it takes {', '.join('smolvm.' + key for key in sorted(_PROFILE_KEYS))}"
            )
        unprivileged = str(params.get("unprivileged", "true")).lower() not in ("false", "0", "no")
        guest_python = str(params.get("python", "")) or _GUEST_PYTHON
        guest_env = [f"{key}={value}" for key, value in all_rules.envs.items()]
        guest_env.append(f"PYTHONPATH={_PACKAGE_DIR.parent}")
        guest_cmd = ["/usr/bin/env", "-i", *guest_env, guest_python, *inner_cmd[1:]]
        socket = ["--expose-socket", f"{_GUEST_SOCKET}:{self.endpoint.path}"] if self.endpoint else []
        cmd = [
            str(smolvm),
            "machine",
            "run",
            "--image",
            self._image(all_rules),
            *(["--unprivileged"] if unprivileged else []),
            *(["--cpus", str(params["cpus"])] if params.get("cpus") else []),
            *(["--mem", str(params["mem"])] if params.get("mem") else []),
            *network_args(all_rules),
            *volume_args(all_rules),
            "-v",
            f"{guest_dir}:{_GUEST_CONFIG_DIR}:ro",
            "-v",
            f"{_PACKAGE_DIR}:{_PACKAGE_DIR}:ro",
            *socket,
            "-w",
            os.getcwd(),
            "--",
            *guest_cmd,
        ]
        q = shlex.quote
        script = "\n".join(
            [
                "umask 077",
                'fifo=""; n=$#',
                'while [ "$n" -gt 0 ]; do',
                "  a=$1; shift; n=$((n-1))",
                '  if [ "$a" = "--_named-pipe" ]; then fifo=$1; shift; n=$((n-1)); else set -- "$@" "$a"; fi',
                "done",
                f'cat "$fifo" > {q(str(guest_dir / "config"))} || exit 99',
                "exec " + " ".join(q(arg) for arg in cmd) + f' "$@" --_named-pipe {_GUEST_CONFIG_DIR}/config',
            ]
        )
        host_env = {"PATH": _HOST_PATH, "HOME": os.environ.get("HOME", "/")}
        host_env.update({key: value for key, value in os.environ.items() if key.startswith("SMOLVM")})
        return ["sh", "-c", script, "smolvm-launcher"], host_env
