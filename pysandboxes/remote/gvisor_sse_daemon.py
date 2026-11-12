# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""gVisor (``runsc``) provider: the sandboxed code runs on a user-space kernel, in a private network.

The launcher (``unshare --user --map-root-user --net``) creates a private user and network namespace.
slirp4netns gives it connectivity and the host loads an ``iptables`` filter into it, then releases the
launcher, which starts ``runsc`` there. The guest shares that namespace (``--network=host``), so the host
kernel enforces the filter on it. No sandboxed code exists before the filter does: a filter that does not
load, or a network that never comes up, kills the launcher instead.
"""

import asyncio
import json
import logging
import os
import select
import signal
import site
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..all_rules import AllRules
from ..e import SandBoxError
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg
from ..override_compat import override
from ..sb_types import Args, ConfigLines, Envs
from ..tools import Environ, follow_links_executable
from .client_subprocess_sse_daemon import BaseSubProcessDaemon, get_log_formatter, use_rich_handler
from .daemon_parameters import DaemonParameters
from .gvisor_bundle import build_oci_spec, exposures, mask_targets
from .gvisor_launch import launcher_script, netfilter_rules, runtime_netfilter_rules
from .runtime_dns import RuntimeDnsSession
from .slirp4netns_common import SLIRP_DNS, SLIRP_WATCHER_TIMEOUT
from .slirp4netns_common import extract_port_forwards as slirp_extract_port_forwards
from .slirp4netns_common import remove_slirp_temp_files as slirp_remove_temp_files
from .slirp4netns_common import run_slirp_watcher as slirp_run_watcher
from .slirp4netns_common import setup_port_forwarding as slirp_setup_port_forwarding
from .tools import which_command

logger = logging.getLogger(__name__)

_REQUIRED_TOOLS = ("runsc", "unshare", "slirp4netns", "iptables-restore", "ip")
_PLATFORMS = ("systrap", "ptrace", "kvm")
_SMOKE_TIMEOUT = 20.0
_TUN_DEVICE = Path("/dev/net/tun")
_KVM_DEVICE = Path("/dev/kvm")
_EMPTY_FILTER = b"*filter\n:INPUT DROP [0:0]\n:OUTPUT DROP [0:0]\nCOMMIT\n"
NETNS_TIMEOUT = 10.0
_HOST_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def wait_for_private_netns(pid: int, timeout: float = NETNS_TIMEOUT, proc: Path = Path("/proc")) -> None:
    """Return once ``pid`` sits in a network namespace of its own, its uid map written.

    slirp4netns attaches to the namespace of the process it is given: attached too early, it would target the
    host's. ``unshare`` creates the namespace and writes the map before it executes the launcher.
    A namespace is identified by the device and inode of its file under ``/proc/<pid>/ns``, not by the text
    of the link, which a guarded ``os.readlink`` rewrites.

    pre: pid > 0
    pre: timeout > 0
    post: __return__ is None
    """
    host_net = _namespace_id(proc / "self" / "ns" / "net")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if (
                _namespace_id(proc / str(pid) / "ns" / "net") != host_net
                and (proc / str(pid) / "uid_map").read_text().strip()
            ):
                return
        except OSError:
            pass
        time.sleep(0.01)
    raise SandBoxError(f"process {pid} never entered a private network namespace")


def _namespace_id(ns_file: Path) -> tuple[int, int]:
    """Return ``(device, inode)`` of a namespace file: equal for the same namespace, different otherwise."""
    info = os.stat(ns_file)
    return info.st_dev, info.st_ino


def _slirp_ready(ready_fd: int, timeout: float) -> bool:
    """True once slirp4netns writes its ready byte; False on timeout, or when it exits first and closes the pipe."""
    readable, _, _ = select.select([ready_fd], [], [], timeout)
    return bool(readable) and os.read(ready_fd, 1) != b""


class GVisorSSEDaemon(BaseSubProcessDaemon):
    """Runs the sandbox daemon in a gVisor guest, on a private network filtered by the host."""

    __slots__ = (
        "_slirp_process_holder",
        "_slirp_shutdown_event",
        "_ready_file",
        "_api_socket",
        "_ports_spec",
        "_dns_session",
    )

    @classmethod
    @override
    def unavailable_reason(cls) -> str | None:
        """Return why gVisor cannot run here, or None: a missing tool or device, a filter that does not load, or a
        guest that does not start.

        post: __return__ is None or len(__return__) > 0
        """
        missing = [tool for tool in _REQUIRED_TOOLS if not which_command(tool)]
        if missing:
            return f"{', '.join(missing)} not found, required for the gvisor provider"
        runsc = which_command("runsc")
        iptables_restore = which_command("iptables-restore")
        assert runsc is not None and iptables_restore is not None
        sidecar = runsc.resolve().parent / "gvisor-bin"
        if not sidecar.is_dir():
            return f"{sidecar} not found: runsc starts from a sidecar directory next to it, install the whole package"
        if not os.access(_TUN_DEVICE, os.R_OK | os.W_OK):
            return f"{_TUN_DEVICE} is not accessible, slirp4netns needs it (in a container: --device /dev/net/tun)"
        in_private_netns = ["unshare", "--user", "--map-root-user", "--net", "--"]
        with tempfile.TemporaryDirectory() as state:
            try:
                loaded = subprocess.run(
                    [*in_private_netns, str(iptables_restore), "--test"],
                    input=_EMPTY_FILTER,
                    capture_output=True,
                    timeout=_SMOKE_TIMEOUT,
                    check=False,
                )
                if loaded.returncode != 0:
                    detail = loaded.stderr.decode(errors="replace").strip()[-300:]
                    return f"iptables-restore cannot load a filter here: {detail}"
                result = subprocess.run(
                    [
                        *in_private_netns,
                        str(runsc),
                        "--ignore-cgroups",
                        "--network=host",
                        f"--root={state}",
                        "do",
                        "/bin/true",
                    ],
                    capture_output=True,
                    timeout=_SMOKE_TIMEOUT,
                    check=False,
                )
            except (subprocess.TimeoutExpired, OSError) as error:
                return f"gvisor could not start a guest: {error}"
        if result.returncode != 0:
            return f"gvisor cannot start a guest: {result.stderr.decode(errors='replace').strip()[-300:]}"
        return None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._slirp_process_holder: list[subprocess.Popen[bytes] | None] = [None]
        self._slirp_shutdown_event: threading.Event = threading.Event()
        self._ready_file: Path = Path()
        self._api_socket: str = ""
        self._ports_spec: str = ""
        self._dns_session = RuntimeDnsSession()

    @override
    def parse_rules(
        self,
        rules: ConfigLines,
        errors: list[ErrorMsg],
    ) -> tuple[ImmutableDict[str, Any], ConfigLines]:
        """Split the ``gvisor.*`` keys from the other lines, which are passed through.

        post: len(__return__[1]) + len(__return__[0]) <= len(rules)
        """
        params: dict[str, str] = {}
        other: ConfigLines = []
        for rule in rules:
            if rule.rule.startswith("gvisor."):
                key, _, value = rule.rule[len("gvisor.") :].partition("=")
                params[key] = value
            else:
                other.append(rule)
        return ImmutableDict(params), other

    @override
    def update_rules_and_activate(self, *, all_rules: AllRules, envs: Envs) -> AllRules:
        """The guest is confined from outside: there is no rule to replace in the child."""
        return all_rules

    @property
    @override
    def base_url(self) -> str:
        """An IP literal: aiohttp resolves a name with AI_ADDRCONFIG, which fails when only ``lo`` has an address."""
        return "http://127.0.0.1:{PORT}"

    @override
    def _sse_bind_host(self, args: Args) -> str:
        """slirp4netns forwards to the address of ``tap0``, not to the loopback of the namespace."""
        return "0.0.0.0"

    @staticmethod
    def _platform(all_rules: AllRules) -> str:
        platform = str(all_rules.os_sandbox_params.get("platform", "")) or "systrap"
        if platform not in _PLATFORMS:
            raise SandBoxError(f"gvisor.platform={platform!r} is not one of {', '.join(_PLATFORMS)}")
        if platform == "kvm" and not os.access(_KVM_DEVICE, os.R_OK | os.W_OK):
            raise SandBoxError(f"gvisor.platform=kvm needs read-write access to {_KVM_DEVICE}")
        return platform

    @staticmethod
    def _runtime_resolv_conf(all_rules: AllRules, work: Path) -> tuple[tuple[str, str], ...]:
        """``net-resolve=runtime``: a ``resolv.conf`` naming the slirp4netns DNS, bound over the one the guest sees.

        The host file usually names a loopback stub that does not exist in the private network namespace. A symlinked
        ``/etc/resolv.conf`` is replaced at the file it resolves to, since a mount cannot land on a link.
        """
        if all_rules.net_resolve != "runtime":
            return ()
        source = work / "resolv.conf"
        source.write_text(f"nameserver {SLIRP_DNS}\n")
        return ((str(source), os.path.realpath("/etc/resolv.conf")),)

    @staticmethod
    def _runtime_paths() -> list[str]:
        """Interpreter, libraries and the directories ``.pth`` files add to ``sys.path``, as ``bwrap`` binds them."""
        chain: set[Path] = set()
        follow_links_executable(Path(sys.executable), chain)
        paths = [str(p) for p in chain] + [str(Path(sys.executable).resolve(strict=True))]
        paths += [p for p in sys.path if p and os.path.isdir(p)]
        paths += [p for p in site.getsitepackages() if os.path.isdir(p)]
        return list(dict.fromkeys(paths))

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Write the bundle, the filter and the launcher script, and return the command that starts them.

        pre: self.port > 0
        post: __return__[0][:4] == ['unshare', '--user', '--map-root-user', '--net']
        """
        inner_cmd, _ = super().subprocess_cmd(all_rules, envs, pipe_path, temp=temp)
        tools = {name: which_command(name) for name in ("ip", "iptables-restore", "runsc")}
        if missing := [name for name, path in tools.items() if path is None]:
            raise SandBoxError(f"{', '.join(missing)} not found, required for the gvisor provider")
        platform = self._platform(all_rules)

        work = temp / "gvisor"
        guest_dir = work / "guest"
        for directory in (work, guest_dir, work / "rootfs"):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        (work / "empty").touch()

        runtime = self._runtime_paths()
        ro, rw = exposures(all_rules, runtime_paths=runtime, guest_dir=str(guest_dir))
        current_dir = os.getcwd()
        python_path = [p for p in runtime if os.path.isdir(p)]
        guest_env = {**dict(all_rules.envs), "PYTHONHOME": sys.base_prefix, "PYTHONPATH": os.pathsep.join(python_path)}
        # runsc, like runc, gives the process HOME=/ when the spec sets none: an environment no rule granted.
        guest_cmd = inner_cmd if "HOME" in guest_env else ["/usr/bin/env", "-u", "HOME", *inner_cmd]
        spec = build_oci_spec(
            rootfs=str(work / "rootfs"),
            args=guest_cmd,
            env={key: str(value) for key, value in guest_env.items()},
            mounts_ro=ro,
            mounts_rw=rw,
            masks=mask_targets(all_rules, current_dir, ro + rw),
            empty_file=str(work / "empty"),
            cwd=current_dir,
            file_binds=self._runtime_resolv_conf(all_rules, work),
        )
        (work / "config.json").write_text(json.dumps(spec))

        self._ready_file = work / "ready"
        self._ready_file.unlink(missing_ok=True)
        self._ports_spec = slirp_extract_port_forwards(all_rules, self.port, log_wildcard=False)
        self._kill_slirp()
        self._slirp_shutdown_event.clear()
        resolver_port = self._dns_session.start(all_rules)
        rules = (
            netfilter_rules(all_rules, self.port)
            if resolver_port is None
            else runtime_netfilter_rules(all_rules, self.port, resolver_port)
        )
        (work / "rules").write_text("\n".join(rules) + "\n")
        fd, api_socket = tempfile.mkstemp()
        os.close(fd)
        os.unlink(api_socket)
        self._api_socket = api_socket

        runsc_argv = [
            str(tools["runsc"]),
            "--ignore-cgroups",
            "--network=host",
            "--host-uds=none",
            f"--platform={platform}",
            f"--root={work / 'state'}",
            "run",
            f"--bundle={work}",
            f"pysb-{uuid.uuid4().hex[:12]}",
        ]
        script = launcher_script(
            ready_file=str(self._ready_file),
            config_fifo=str(pipe_path),
            config_copy=str(guest_dir / "config"),
            rules_file=str(work / "rules"),
            spec_file=str(work / "config.json"),
            python=sys.executable,
            ip=str(tools["ip"]),
            iptables_restore=str(tools["iptables-restore"]),
            runsc_argv=runsc_argv,
        )
        args: Args = ["unshare", "--user", "--map-root-user", "--net", "--", "sh", "-c", script, "gvisor-launcher"]
        return args, {"PATH": _HOST_PATH}

    @override
    def _on_process_launched(self, pid: int) -> None:
        """Bring the private network up, then release the launcher; kill it if the network never comes up.

        The launcher waits for ``ready_file`` before it loads the filter and starts the guest, so no
        sandboxed code runs before both exist.

        pre: pid > 0
        post: self._ready_file.exists()
        """
        read_fd, write_fd = os.pipe()
        try:
            wait_for_private_netns(pid)
            self._dns_session.attach(pid)
            threading.Thread(
                target=slirp_run_watcher,
                args=(self._slirp_shutdown_event, write_fd, self._api_socket),
                kwargs={
                    "child_pid": pid,
                    "process_holder": self._slirp_process_holder,
                    "timeout": SLIRP_WATCHER_TIMEOUT,
                },
                daemon=True,
            ).start()
            if not _slirp_ready(read_fd, SLIRP_WATCHER_TIMEOUT):
                raise SandBoxError("slirp4netns never brought up the gvisor sandbox network")
        except BaseException:
            self._dns_session.stop()
            self._slirp_shutdown_event.set()
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            raise
        finally:
            os.close(read_fd)
        self._ready_file.touch()
        if self._ports_spec:
            threading.Thread(
                target=slirp_setup_port_forwarding, args=(self._api_socket, self._ports_spec), daemon=True
            ).start()

    def get_launch_params_for_python_sb(
        self,
        all_rules: AllRules,
        log_level: int,
        token: str,
        init_fn: str,
        pipe_path: Path,
        temp: Path,
    ) -> dict[str, Any]:
        """Return the config of the ``python-sb`` launch path: the daemon binds every interface for slirp."""
        process_config = DaemonParameters(
            all_rules=all_rules,
            log_level=log_level,
            log_format=get_log_formatter(),
            use_rich_handler=use_rich_handler(),
            token=token,
            port=self.port,
            init_fn=init_fn,
            netfilter_rules=(),
            bind_host="0.0.0.0",
        )
        return {"process_config": process_config, "on_launched": self._on_process_launched}

    def _kill_slirp(self) -> None:
        """Stop slirp4netns, which outlives its target and keeps the forwarded host ports, and remove its socket.

        The filtering resolver of ``net-resolve=runtime`` stops with it.
        """
        self._dns_session.stop()
        self._slirp_shutdown_event.set()
        proc = self._slirp_process_holder[0]
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                logger.debug("slirp4netns is already gone, or refuses to die")
            self._slirp_process_holder[0] = None
        slirp_remove_temp_files(None, self._api_socket)

    @override
    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        self._slirp_shutdown_event.set()
        try:
            await super()._shutdown(graceful_shutdown)
        finally:
            await asyncio.to_thread(self._kill_slirp)
