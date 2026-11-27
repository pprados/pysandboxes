# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""docker-sandbox provider: the sandboxed code runs in a microVM of Docker Sandboxes (``sbx``).

A launcher process (``docker_sandbox_launcher.py``) creates the sandbox with its mounts, ports and network rules, runs
the payload in it through ``sbx exec`` as an unprivileged user with no capability, and removes the sandbox when it
ends. The guest template holds the interpreter and the dependencies; the package of the host is mounted read-only.
The channel is the HTTP/SSE port published by ``sbx``. The config never touches the disk: it goes from the host FIFO
to the standard input of the payload.
"""

import json
import logging
import os
import re
import shlex
import subprocess
import sys
import uuid
from functools import lru_cache
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
from .docker_sandbox_rules import guest_python_path, is_image_owned, mask_targets, mounts, sbx_rules
from .tools import which_command

logger = logging.getLogger(__name__)

_TEMPLATE_ENV = "PYSANDBOXES_DOCKER_SANDBOX_TEMPLATE"
_PACKAGE_DIR = Path(__file__).resolve().parent.parent
_LAUNCHER = Path(__file__).with_name("docker_sandbox_launcher.py")
_GUEST_FALLBACK_PACKAGE = "/opt/pysb/pysandboxes"
_GUEST_PYTHON = "/usr/local/bin/python"
_MIN_VERSION = (0, 51, 0)
_PAYLOAD_ID = 2000
_WRONG_PYTHON = 72
_CANARY = "pysb-canary.invalid:443"
_PROFILE_KEYS = frozenset({"template", "python", "cpus", "mem", "proxy"})
_HOST_ENV_PREFIXES = ("SBX", "DOCKER", "XDG_", "DBUS_")
_PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
)
_PROXY_GUARD_RULE = "net=ALLOW|TCP|gateway.docker.internal|3128|OUT"
_SANDBOX_PREFIX = "pysb-"
_PASSWD_HOME = "/tmp"
# The image has no ``mount`` binary: the masks go through mount(2). A file is hidden by binding /dev/null over it, a
# directory by a read-only empty tmpfs.
_MASK_CODE = """\
import ctypes, json, sys
libc = ctypes.CDLL(None, use_errno=True)
MS_RDONLY, MS_BIND = 1, 4096
for path, is_directory in json.loads(sys.argv[1]):
    if is_directory:
        done = libc.mount(b"tmpfs", path.encode(), b"tmpfs", MS_RDONLY, None)
    else:
        done = libc.mount(b"/dev/null", path.encode(), None, MS_BIND, None)
    if done != 0:
        sys.exit("docker-sandbox: cannot mask " + path + ": errno " + str(ctypes.get_errno()))
"""


@lru_cache(maxsize=1)
def _probe() -> str | None:
    """Return why ``sbx`` cannot run sandboxes here, or None; read-only and never interactive."""
    sbx = which_command("sbx")
    if sbx is None:
        return "sbx not found, required for the docker-sandbox provider (Docker Sandboxes)"
    try:
        version = subprocess.run([str(sbx), "version"], capture_output=True, text=True, timeout=30, check=False)
        found = re.search(r"v?(\d+)\.(\d+)\.(\d+)", version.stdout)
        if found is None or tuple(int(part) for part in found.groups()) < _MIN_VERSION:
            return f"sbx {'.'.join(map(str, _MIN_VERSION))} or later is required"
        diagnose = subprocess.run(
            [str(sbx), "--no-input", "diagnose", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        failed = [
            check.get("name", "?")
            for check in _checks(diagnose.stdout)
            if check.get("name") in ("virtualization", "authentication", "global-network-policy", "daemon")
            and check.get("status", check.get("result")) not in ("pass", "ok", "passed")
        ]
        if failed:
            return f"sbx diagnose fails on {', '.join(failed)} (sbx login, sbx daemon, sbx policy init)"
        policy = subprocess.run(
            [str(sbx), "--no-input", "policy", "ls"], capture_output=True, text=True, timeout=30, check=False
        )
        if policy.returncode != 0:
            return "sbx has no network policy preset: run `sbx policy init deny-all`"
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"sbx does not answer: {error}"
    return None


def _checks(output: str) -> list[dict[str, Any]]:
    """The checks of ``sbx diagnose --format json``, whatever the nesting."""
    try:
        data = json.loads(output)
    except ValueError:
        return []
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "name" in node and ("status" in node or "result" in node):
                found.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return found


def guest_script(
    *,
    masks: list[tuple[str, bool]],
    cwd: str,
    env: dict[str, str],
    inherited: tuple[str, ...],
    command: list[str],
    python_version: tuple[int, int],
) -> str:
    """Return the ``sh`` script the guest runs as root: check Python, mask, create the user, drop every right, run.

    The guest must run the Python of the host, as the guard code runs on the interpreter that wrote the config: a
    guest of another version stops with ``_WRONG_PYTHON`` before the payload starts. The payload runs as a fixed
    unprivileged user with no capability and ``no_new_privs``, so a mask laid down here cannot be undone. ``inherited``
    names variables of the sandbox the payload keeps (the proxy ones); ``"$@"`` carries the caller's arguments.
    """
    q = shlex.quote
    major, minor = python_version
    probe = f"import sys; sys.exit(0 if sys.version_info[:2] == ({major}, {minor}) else 1)"
    lines = [
        "set -e",
        f"{q(command[0])} -c {q(probe)} || "
        f'{{ echo "docker-sandbox: the guest does not run Python {major}.{minor} as the host does: '
        f'rebuild the template with PYTHON_VERSION={major}.{minor}" >&2; exit {_WRONG_PYTHON}; }}',
        f"grep -q '^sandbox:' /etc/passwd || "
        f"echo 'sandbox:x:{_PAYLOAD_ID}:{_PAYLOAD_ID}::{_PASSWD_HOME}:/bin/sh' >> /etc/passwd",
        f"grep -q '^sandbox:' /etc/group || echo 'sandbox:x:{_PAYLOAD_ID}:' >> /etc/group",
    ]
    if masks:
        lines.append(f"{q(command[0])} -c {q(_MASK_CODE)} {q(json.dumps(masks))}")
    lines.append(f"cd {q(cwd)} 2>/dev/null || {{ mkdir -p {q(cwd)} && cd {q(cwd)}; }}")
    drop = [
        "setpriv",
        f"--reuid={_PAYLOAD_ID}",
        f"--regid={_PAYLOAD_ID}",
        "--clear-groups",
        "--bounding-set=-all",
        "--inh-caps=-all",
        "--no-new-privs",
    ]
    clean_env = [f"{key}={q(value)}" for key, value in env.items()]
    clean_env += [f'${{{name}:+{name}="${name}"}}' for name in inherited]
    lines.append(" ".join(["exec", *drop, "env", "-i", *clean_env, *(q(c) for c in command), '"$@"']))
    return "\n".join(lines) + "\n"


class DockerSandboxSSEDaemon(BaseSubProcessDaemon):
    """Runs the sandbox daemon in a Docker Sandboxes microVM, reached through a published TCP port."""

    __slots__ = ("_previous",)
    supports_unix_endpoint = False
    endpoint_handed_down = True

    @classmethod
    @override
    def unavailable_reason(cls) -> str | None:
        """Return why Docker Sandboxes cannot run here, or None.

        post: __return__ is None or len(__return__) > 0
        """
        return _probe()

    @override
    def parse_rules(
        self,
        rules: ConfigLines,
        errors: list[ErrorMsg],
    ) -> tuple[ImmutableDict[str, Any], ConfigLines]:
        """Split the ``docker-sandbox.*`` keys from the other lines, which are passed through.

        post: len(__return__[1]) + len(__return__[0]) <= len(rules)
        """
        params: dict[str, str] = {}
        other: ConfigLines = []
        for rule in rules:
            if rule.rule.startswith("docker-sandbox."):
                key, _, value = rule.rule[len("docker-sandbox.") :].partition("=")
                params[key] = value
            else:
                other.append(rule)
        return ImmutableDict(params), other

    @override
    def update_rules_and_activate(self, *, all_rules: AllRules, envs: Envs) -> AllRules:
        """Let the Python layer read what the guest runs on, and reach the proxy of ``sbx`` when the profile asks.

        The guest is confined from outside, so this adds, ahead of the user's rules, read access to the guest's
        interpreter and to the package. The rules name the host's interpreter, not the image's.
        """
        implicit = tuple(
            FSExposeRule(path, False, ConfigLine("<implicit docker-sandbox guest>", Path(__file__), 0))
            for path in (f"{Path(_GUEST_PYTHON).parent.parent}/", f"{_PACKAGE_DIR}/")
        )
        socket_rules = all_rules.socket_rules
        if str(all_rules.os_sandbox_params.get("proxy", "false")).lower() == "true":
            from ..guard_socket import SocketRules
            from ..guard_socket import parse_rules as socket_parse_rules

            extra, *_ = socket_parse_rules([ConfigLine(_PROXY_GUARD_RULE, Path(__file__), 0)], [])
            socket_rules = SocketRules([*socket_rules, *extra])
        return all_rules._replace(file_rules=(*implicit, *all_rules.file_rules), socket_rules=socket_rules)

    @override
    def _sse_bind_host(self, args: Args) -> str:
        """The guest cannot be reached on its loopback: the published port lands on the guest's own address."""
        return "0.0.0.0"  # noqa: S104

    @staticmethod
    def _template(all_rules: AllRules) -> str:
        """The guest template: the ``docker-sandbox.template`` key, else ``PYSANDBOXES_DOCKER_SANDBOX_TEMPLATE``,
        else the one ``make build-image-docker-sandbox`` builds for this Python minor."""
        return (
            str(all_rules.os_sandbox_params.get("template", ""))
            or os.environ.get(_TEMPLATE_ENV, "")
            or f"pysandboxes-guest:{sys.version_info.major}.{sys.version_info.minor}"
        )

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Return the launcher command: it creates the sandbox, runs the payload and removes the sandbox.

        What the caller appends to the command line, minus the pipe, is the guest's: the user's arguments of
        ``python-sb``.
        """
        sbx = which_command("sbx")
        if sbx is None:
            raise SandBoxError("sbx not found, required for the docker-sandbox provider")
        inner_cmd, _ = super().subprocess_cmd(all_rules, envs, pipe_path, temp=temp)
        params = all_rules.os_sandbox_params
        if unknown := sorted(set(params.keys()) - _PROFILE_KEYS):
            raise SandBoxError(
                f"docker-sandbox does not know {', '.join('docker-sandbox.' + key for key in unknown)}; "
                f"it takes {', '.join('docker-sandbox.' + key for key in sorted(_PROFILE_KEYS))}"
            )
        proxy = str(params.get("proxy", "false")).lower() == "true"
        cwd = os.getcwd()
        shared = mounts(all_rules, extra_ro=[])
        workspace = shared.rw[0] if shared.rw else str(temp / "workspace")
        if not shared.rw:
            (temp / "workspace").mkdir(exist_ok=True)
        extra_rw = [path for path in shared.rw if path != workspace]
        guest_env = {key: str(value) for key, value in all_rules.envs.items()}
        guest_package = _GUEST_FALLBACK_PACKAGE if is_image_owned(str(_PACKAGE_DIR)) else str(_PACKAGE_DIR)
        exposed = [*shared.ro, *shared.rw]
        python_path = guest_python_path(sys.path, exposed, cwd)
        guest_env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys([str(Path(guest_package).parent), *python_path]))
        guest_python = str(params.get("python", "")) or _GUEST_PYTHON
        name = f"{_SANDBOX_PREFIX}{os.getpid()}-{uuid.uuid4().hex[:8]}"
        rules = sbx_rules(all_rules)
        create = [
            "shell",
            "--name",
            name,
            "--no-progress",
            "--pull",
            "never",
            "-t",
            self._template(all_rules),
            "-p",
            f"127.0.0.1:{self.port}:{self.port}",
            *(["--cpus", str(params["cpus"])] if params.get("cpus") else []),
            *(["-m", str(params["mem"])] if params.get("mem") else []),
            workspace,
            *(f"{path}" for path in extra_rw),
            *(f"{path}:{path}:ro" for path in shared.ro),
            f"{_PACKAGE_DIR}:{guest_package}:ro",
        ]
        stale = [previous] if (previous := getattr(self, "_previous", None)) else []
        self._previous = name
        plan = {
            "name": name,
            "stale": stale,
            "parent": os.getpid(),
            "path": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "create": create,
            "allow": list(rules.allow),
            "deny": list(rules.deny),
            "allow_checks": list(rules.allow),
            "canary": _CANARY,
            "script": guest_script(
                masks=mask_targets(all_rules, cwd, exposed),
                cwd=cwd,
                env=guest_env,
                inherited=_PROXY_VARIABLES if proxy else (),
                command=[guest_python, *inner_cmd[1:], "--_config-on-stdin"],
                python_version=(sys.version_info.major, sys.version_info.minor),
            ),
        }
        host_env = {
            key: value
            for key, value in os.environ.items()
            if key in ("PATH", "HOME") or key.startswith(_HOST_ENV_PREFIXES)
        }
        return [sys.executable, "-I", str(_LAUNCHER), json.dumps(plan)], host_env
