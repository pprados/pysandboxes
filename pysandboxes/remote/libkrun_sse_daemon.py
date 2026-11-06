# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""libkrun-based daemon for OS-level sandboxing with PySandboxes."""

import asyncio
import gc
import json
import logging
import os
import pickle
import select
import shlex
import subprocess
import sys
import tempfile
import threading
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any

from aiohttp import ClientConnectorError, ClientOSError, ClientTimeout, ServerDisconnectedError

from ..all_rules import AllRules
from ..e import SandBoxError
from ..guard_files import FSExposeRule
from ..guard_socket import Action, Direction
from ..netfilter import rule_to_netfilter
from ..sb_types import Args, ConfigLine, Envs
from ..tools import Environ, get_callable_info
from .client_subprocess_sse_daemon import (
    BaseSubProcessDaemon,
    get_log_formatter,
    launch_sandbox,
    use_rich_handler,
)
from .daemon_parameters import DaemonParameters
from .endpoint import UNIX, Endpoint, format_endpoint
from .endpoint_connector import ENDPOINT_URL, make_session
from .libkrun_ffi import find_libkrun, find_libkrunfw
from .libkrun_launcher import ERROR_FILE_NAME, GUEST_SOCKET, READY_FILE_NAME
from .parameters import INTERVAL_FOR_PING_DAEMON, LOOP_FOR_PING, TIMEOUT_FOR_PING
from .slirp4netns_common import (
    SLIRP_DNS,
    SLIRP_WATCHER_TIMEOUT,
    remove_slirp_temp_files,
    run_slirp_watcher,
)
from .tools import SSE_READ_BUFSIZE, is_transient_connection_error, which_command

logger = logging.getLogger(__name__)


# The guest has addresses of its own: ``SLIRP_GW`` stays the slirp4netns gateway, which reaches the host loopback, and
# ``passt`` would turn its own gateway into the loopback of the private namespace.
_GUEST_ADDR = "10.0.2.200"
_GUEST_GW = "10.0.2.254"
_NET_TOOLS = ("unshare", "slirp4netns", "iptables-restore", "ip", "passt")
_HOST_PATH = "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def _wants_network(all_rules: AllRules) -> bool:
    """True when a ``net=`` rule lets the guest open outgoing connections: without one, the guest gets no NIC at all."""
    return any(rule.action == Action.ALLOW and Direction.OUT in rule.directions for rule in all_rules.socket_rules)


def _slirp_ready(ready_fd: int, timeout: float) -> bool:
    """True once slirp4netns writes its ready byte; False on timeout, or when it exits first and closes the pipe."""
    readable, _, _ = select.select([ready_fd], [], [], timeout)
    return bool(readable) and os.read(ready_fd, 1) != b""


def _passt_script(
    *, ready_file: str, pid_file: str, rules_file: str, ip: str, iptables_restore: str, passt: str
) -> str:
    """The ``sh -c`` script of the process that holds the guest's network, run in a private network namespace.

    The micro-VM itself stays outside: it only talks to ``passt`` through the descriptor ``$PASST_FD``. ``passt``
    starts once the filter is loaded and exits when it does not load, so no guest packet is ever relayed
    unfiltered, whatever the guest runs: every connection ``passt`` opens crosses this namespace's ``OUTPUT`` chain.
    """
    q = shlex.quote
    return "\n".join(
        [
            "umask 077",
            f"echo $$ > {q(pid_file)}",
            f"until [ -e {q(ready_file)} ]; do sleep 0.05; done",
            f"{q(ip)} link set lo up || exit 97",
            f"{q(iptables_restore)} < {q(rules_file)} || exit 98",
            f'exec {q(passt)} -f -4 -F "$PASST_FD" -a {_GUEST_ADDR} -n 255.255.255.0 -g {_GUEST_GW} --no-dhcp-search',
        ]
    )


class LibkrunSSEDaemon(BaseSubProcessDaemon):
    """Runs the sandbox daemon in a KVM micro-VM; the network, when a rule allows it, is filtered by the host."""

    __slots__ = ("_slirp_holder", "_slirp_event", "_ready_file", "_pid_file", "_api_socket")
    supports_unix_endpoint = True
    endpoint_handed_down = False

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._slirp_holder: list[subprocess.Popen[bytes] | None] = [None]
        self._slirp_event = threading.Event()
        self._ready_file: Path | None = None
        self._pid_file = ""
        self._api_socket = ""

    @classmethod
    def unavailable_reason(cls) -> str | None:
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            return "host lacks read/write access to /dev/kvm"
        if not find_libkrun():
            return "libkrun shared library not found"
        if not find_libkrunfw():
            return "libkrunfw shared library not found"
        return None

    def _choose_endpoint(self, all_rules: AllRules) -> None:
        """Require a Unix endpoint: libkrun relays a host Unix socket to the guest, it has no TCP forward."""
        super()._choose_endpoint(all_rules)
        if self.endpoint is None:
            raise SandBoxError(
                "The libkrun provider needs a Unix socket: use remote-endpoint=auto or unix, no fixed port."
            )

    def get_launch_params_for_python_sb(
        self, all_rules: AllRules, log_level: int, token: str, init_fn: str, pipe_path: Path, temp: Path
    ) -> dict[str, Any]:
        """Hand the configuration to the guest as a plain file: a FIFO does not cross virtiofs."""
        return {
            "config_writer": lambda cfg: pipe_path.write_bytes(pickle.dumps(cfg)),
            "on_launched": self._on_process_launched,
        }

    async def _wait_guest_listening(self, ready_file: Path) -> None:
        """Wait for the guest listener: libkrun aborts when the host connects before anything listens."""
        for _ in range(LOOP_FOR_PING):
            if ready_file.exists():
                return
            if self._process is not None and self._process.returncode is not None:
                error_file = ready_file.parent / ERROR_FILE_NAME
                detail = error_file.read_text(encoding="utf-8")[-1500:] if error_file.exists() else ""
                raise SandBoxError(
                    f"The libkrun micro-VM exited with {self._process.returncode} before the guest listened. {detail}"
                )
            await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)
        raise SandBoxError("The libkrun guest never started listening.")

    def subprocess_cmd(self, all_rules: AllRules, envs: Environ, pipe_path: Path, temp: Path) -> tuple[Args, Environ]:
        guest_cmd, extra_env = super().subprocess_cmd(all_rules, envs, pipe_path, temp=temp)

        mounts: list[dict[str, Any]] = []
        # The root is already shared read-only, but the guest mounts a private tmpfs on /tmp, so a directory under
        # it needs its own share, whatever its mode.
        write_access: dict[Path, bool] = {}
        for rule in all_rules.file_rules:
            if isinstance(rule, FSExposeRule):
                resolved = Path(rule.path).resolve(strict=False)
                write_access[resolved] = write_access.get(resolved, False) or rule.write
        for resolved in sorted((p for p in write_access if p.is_dir()), key=lambda p: len(p.parts)):
            mounts.append(
                {
                    "tag": f"fs_{len(mounts)}",
                    "host_path": str(resolved),
                    "guest_path": str(resolved),
                    "readonly": not write_access[resolved],
                }
            )

        if self.endpoint is not None:
            # A launcher killed by a signal leaves its socket behind, and libkrun does not bind over a stale one.
            Path(self.endpoint.path).unlink(missing_ok=True)
        net = None
        launcher: Args = [
            sys.executable,
            "-m",
            "pysandboxes.remote.libkrun_launcher",
            "--config",
            str(temp / "libkrun_config.json"),
        ]
        if _wants_network(all_rules):
            tools = {name: which_command(name) for name in _NET_TOOLS}
            if missing := [name for name, path in tools.items() if path is None]:
                raise SandBoxError(f"{', '.join(missing)} not found, required for libkrun network rules")
            rules = rule_to_netfilter(all_rules.socket_rules, [IPv4Address(SLIRP_DNS)], is_ipv6=False)
            (temp / "net.rules").write_text("\n".join(rules) + "\n")
            self._ready_file = temp / "net.ready"
            self._ready_file.unlink(missing_ok=True)
            self._kill_slirp()
            self._slirp_event.clear()
            fd, self._pid_file = tempfile.mkstemp()
            os.close(fd)
            fd, self._api_socket = tempfile.mkstemp()
            os.close(fd)
            os.unlink(self._api_socket)
            script = _passt_script(
                ready_file=str(self._ready_file),
                pid_file=self._pid_file,
                rules_file=str(temp / "net.rules"),
                ip=str(tools["ip"]),
                iptables_restore=str(tools["iptables-restore"]),
                passt=str(tools["passt"]),
            )
            net = {
                "address": _GUEST_ADDR,
                "prefix": "24",
                "gateway": _GUEST_GW,
                "dns": SLIRP_DNS,
                "cmd": ["unshare", "--user", "--map-root-user", "--net", "--", "sh", "-c", script, "libkrun-passt"],
                "env": {"PATH": _HOST_PATH},
            }
        config = {
            "net": net,
            "vcpus": 1,
            "ram_mib": 512,
            "root_dir": "/",
            "run_dir": str(temp),
            "mounts": mounts,
            "guest_cmd": guest_cmd,
            "envs": {**({**os.environ, **all_rules.envs} if all_rules.learn else dict(all_rules.envs)), **extra_env},
            "port": self.port if self.endpoint else 0,
            "unix_socket": self.endpoint.path if self.endpoint else None,
        }
        (temp / "libkrun_config.json").write_text(json.dumps(config), encoding="utf-8")
        return launcher, extra_env

    def _on_process_launched(self, pid: int) -> None:
        """Attach slirp4netns to the namespace of the launcher, then release it; kill it if no network comes up."""
        if self._ready_file is None:
            return
        read_fd, write_fd = os.pipe()
        try:
            threading.Thread(
                target=run_slirp_watcher,
                args=(self._slirp_event, write_fd, self._api_socket),
                kwargs={
                    "pid_file": self._pid_file,
                    "process_holder": self._slirp_holder,
                    "timeout": SLIRP_WATCHER_TIMEOUT,
                },
                daemon=True,
            ).start()
            if not _slirp_ready(read_fd, SLIRP_WATCHER_TIMEOUT):
                raise SandBoxError("slirp4netns never brought up the libkrun sandbox network")
        except BaseException:
            self._slirp_event.set()
            try:
                os.kill(pid, 9)
            except OSError:
                pass
            raise
        finally:
            os.close(read_fd)
        self._ready_file.touch()

    def _kill_slirp(self) -> None:
        """Stop slirp4netns, which outlives its target, and remove its temporary files."""
        self._slirp_event.set()
        proc = self._slirp_holder[0]
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                logger.debug("slirp4netns is already gone, or refuses to die")
            self._slirp_holder[0] = None
        remove_slirp_temp_files(self._pid_file or None, self._api_socket or None)

    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        self._kill_slirp()
        await super()._shutdown(graceful_shutdown)

    async def _re_start_cmd(
        self,
        all_rules: AllRules,
        args: Args,
        extra_envs: Environ,
        pipe_path: Path,
        port: int,
        *,
        log_level: int,
        init_fn: Any,
    ) -> None:
        self._is_started = False
        self._accept_incoming = False
        init_fn_ref = ""
        if init_fn:
            module, func_ref = get_callable_info(init_fn)
            init_fn_ref = f"{module}:{func_ref}"

        process_config = DaemonParameters(
            all_rules=all_rules._replace(
                file_rules=(*all_rules.file_rules, FSExposeRule(GUEST_SOCKET, True, ConfigLine("<libkrun>", Path(), 0)))
            ),
            log_level=log_level,
            log_format=get_log_formatter(),
            use_rich_handler=use_rich_handler(),
            token=self._token,
            port=port,
            init_fn=init_fn_ref,
            endpoint=format_endpoint(Endpoint(UNIX, path=GUEST_SOCKET)),
        )

        assert self.endpoint is not None
        env: Environ = {**os.environ, **all_rules.envs} if all_rules.learn else dict(all_rules.envs)
        env = {**env, **extra_envs}

        launch_kwargs: dict[str, Any] = dict(
            cmd=[*args, "--_named-pipe", str(pipe_path)],
            pipe_path=pipe_path,
            envs=Envs(env),
            process_config=process_config,
            config_writer=lambda cfg: pipe_path.write_bytes(pickle.dumps(cfg)),
            stdin=subprocess.DEVNULL,
            on_launched=self._on_process_launched,
        )

        logger.debug("Launch process: %s", " ".join((repr(c) if " " in c else c for c in launch_kwargs["cmd"])))
        self._process = await launch_sandbox(**launch_kwargs)
        ping_url = ENDPOINT_URL + "/ping"
        logger.info("Subprocess launched (pid=%s), pinging %s", self._process.pid, ping_url)
        try:
            await self._on_process_started()
        except Exception:
            raise
        logger.info("Pinging subprocess daemon at %s", ping_url)
        gc.collect()
        await self._wait_guest_listening(pipe_path.parent / READY_FILE_NAME)
        async with make_session(self.endpoint, read_bufsize=SSE_READ_BUFSIZE) as session:
            count_loop = 0
            while True:
                try:
                    count_loop += 1
                    if count_loop > LOOP_FOR_PING:
                        logger.error("Is not possible to connect to the sandbox daemon (%s)", ping_url)
                        raise SandBoxError(f"The libkrun sandbox daemon never answered on {ping_url}.")
                    async with session.get(ping_url, timeout=ClientTimeout(total=TIMEOUT_FOR_PING)) as response:
                        if response.status == 200:
                            break
                        raise RuntimeError(f"Unexpected status {response.status} from {ping_url}")
                except TimeoutError:
                    if count_loop % 15 == 0:
                        logger.info("Ping attempt %d/%d: timeout", count_loop, LOOP_FOR_PING)
                except (ClientConnectorError, ServerDisconnectedError):
                    if count_loop % 15 == 0:
                        logger.info("Ping attempt %d/%d: connection failed", count_loop, LOOP_FOR_PING)
                except ClientOSError as e:
                    if not is_transient_connection_error(e):
                        raise
                    if count_loop % 15 == 0:
                        logger.info("Ping attempt %d/%d: %s", count_loop, LOOP_FOR_PING, type(e).__name__)
                await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)
        await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)
        logger.info("Subprocess daemon is up and running at %s", ping_url)
        self._is_started = True
        self._accept_incoming = True
