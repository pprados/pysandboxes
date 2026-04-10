# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Bubblewrap (bwrap) based daemon for OS-level sandboxing with PySandboxes.

This module implements a bwrap-based sandbox daemon that combines
PySandboxes Python-level security with bubblewrap OS-level isolation.
It loads a bwrap template, translates file rules to bind mounts,
and launches the sandboxed Python process. When socket rules are present,
uses --unshare-net with slirp4netns and iptables for user-land network filtering.
"""

import asyncio
import fnmatch
import gc
import importlib.resources
import json
import logging
import os
import shlex
import site
import socket as socket_mod
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, cast

import aiohttp
from aiohttp import ClientConnectorError, ClientTimeout, ServerDisconnectedError

from ..all_rules import AllRules
from ..guard_files import BindRule, IgnoreRule
from ..guard_socket import Action, Direction, Kind
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg, pysandboxes_logger
from ..netfilter import rule_to_netfilter
from ..override_compat import override
from ..sb_types import Args, ConfigLines, Envs
from ..tools import (
    Environ,
    follow_links_executable,
    remove_comments,
    substitute_env_vars,
)
from .client_subprocess_sse_daemon import (
    BaseSubProcessDaemon,
    DaemonParameters,
    find_free_port,
    get_callable_info,
    get_log_formatter,
    launch_sandbox,
    use_rich_handler,
)
from .parameters import (
    INTERVAL_FOR_PING_DAEMON,
    LOOP_FOR_PING,
    TIMEOUT_FOR_PING,
)
from .tools import suggest_package_installation, which_command

logger = logging.getLogger(__name__)

# slirp4netns guest addressing (same as unshare)
SLIRP_GW = "10.0.2.2"
SLIRP_DNS = "10.0.2.3"
SLIRP_INTERFACE = "tap0"
SLIRP_WATCHER_TIMEOUT = 30


def _is_socket(path: str) -> bool:
    """Return True if path is a Unix socket."""
    try:
        return stat.S_ISSOCK(os.stat(path).st_mode)
    except (OSError, ValueError):
        return False


def _resolve_ignore_paths(
    current_dir: str,
    ignore_rules: list[IgnoreRule],
) -> list[str]:
    """Resolve ignore rules to paths relative to current_dir (same semantics as unshare)."""
    if not ignore_rules:
        return []
    patterns = [r.source for r in ignore_rules]
    result: list[str] = []
    try:
        cur = Path(current_dir).resolve()
        for root, _dirs, files in os.walk(cur):
            root_path = Path(root)
            for name in list(_dirs) + files:
                if any(fnmatch.fnmatch(name, p) for p in patterns):
                    rel = root_path / name
                    try:
                        rel = rel.relative_to(cur)
                    except ValueError:
                        continue
                    result.append(str(rel))
    except OSError:
        pass
    return result


class BWrapSSEDaemon(BaseSubProcessDaemon):
    """Bubblewrap-based subprocess daemon for OS-level sandboxing.

    Translates PySandboxes rules to bwrap arguments and launches
    sandboxed processes. When socket rules exist, uses --unshare-net with
    slirp4netns and iptables so network filtering runs in user-land.
    """

    __slots__ = (
        "_slirp_process",
        "_slirp_shutdown_event",
        "_slirp_api_socket",
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._slirp_process: subprocess.Popen[bytes] | None = None
        self._slirp_shutdown_event: threading.Event = threading.Event()
        self._slirp_api_socket: str = ""

    @staticmethod
    def _use_network_filtering(all_rules: AllRules) -> bool:
        """True when socket rules exist and bwrap should use unshare-net + iptables."""
        if not all_rules.socket_rules:
            return False
        # Allow config to disable: bwrap.share-net=yes or bwrap.unshare-net=no
        params = all_rules.os_sandbox_params
        if params.get("share-net"):
            return False
        if str(params.get("unshare-net", "")).lower() in ("no", "0", "false"):
            return False
        return True

    @staticmethod
    def _build_netfilter_rules(all_rules: AllRules, port: int) -> tuple[str, ...]:
        """Build iptables rules from socket rules; DNS 10.0.2.3, allow SSE from 10.0.2.2."""
        from ipaddress import IPv4Address

        dns_guest = [IPv4Address(SLIRP_DNS)]
        netfilter = rule_to_netfilter(all_rules.socket_rules, dns_guest, is_ipv6=False)
        if "COMMIT" in netfilter:
            idx = netfilter.index("COMMIT")
            sse_allow = (
                f"-A INPUT -p tcp -s {SLIRP_GW}/32 --dport {port} "
                "-m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT"
            )
            netfilter = list(netfilter[:idx]) + [sse_allow] + list(netfilter[idx:])
        return tuple(netfilter)

    def _extract_port_forwards(self, all_rules: AllRules) -> str:
        """Port forwarding spec for slirp4netns (e.g. 'tcp:PORT tcp:80')."""
        tcp_ports: set[int] = {self.port}
        udp_ports: set[int] = set()
        for rule in all_rules.socket_rules:
            if rule.action != Action.ALLOW or Direction.IN not in rule.directions:
                continue
            ports = rule.mask.ports
            if isinstance(ports, range) and len(ports) > 1000:
                continue
            for p in list(ports):
                for kind in rule.mask.kinds:
                    if kind == Kind.TCP:
                        tcp_ports.add(p)
                    elif kind == Kind.UDP:
                        udp_ports.add(p)
        parts = [f"tcp:{p}" for p in sorted(tcp_ports)]
        parts += [f"udp:{p}" for p in sorted(udp_ports)]
        return " ".join(parts)

    def _slirp_watcher(self, pipe_w: int, api_socket: str, child_pid: int) -> None:
        """Background: run slirp4netns for child_pid, signal readiness on pipe_w."""
        deadline = time.monotonic() + SLIRP_WATCHER_TIMEOUT
        while not self._slirp_shutdown_event.is_set():
            if time.monotonic() > deadline:
                logger.error(
                    "slirp_watcher: timed out waiting after %ds",
                    SLIRP_WATCHER_TIMEOUT,
                )
                try:
                    os.close(pipe_w)
                except OSError:
                    pass
                return
            try:
                slirp_arg = [
                    "slirp4netns",
                    "-c",
                    "-m",
                    "1500",
                    "-r",
                    str(pipe_w),
                    "--api-socket",
                    api_socket,
                    str(child_pid),
                    SLIRP_INTERFACE,
                ]
                logger.debug("slirp_watcher: launching: %s", " ".join(slirp_arg))
                proc = subprocess.Popen(
                    slirp_arg,
                    stdout=subprocess.DEVNULL,
                    stderr=(
                        subprocess.PIPE
                        if logger.isEnabledFor(logging.DEBUG)
                        else subprocess.DEVNULL
                    ),
                    pass_fds=(pipe_w,),
                )
                self._slirp_process = proc
                logger.debug("slirp_watcher: slirp4netns launched (pid=%s)", proc.pid)
                while True:
                    try:
                        proc.wait(timeout=1.0)
                        break
                    except subprocess.TimeoutExpired:
                        if self._slirp_shutdown_event.is_set():
                            return
                if proc.returncode and proc.returncode != -9:
                    logger.warning(
                        "slirp_watcher: slirp4netns exited with code %s",
                        proc.returncode,
                    )
            except Exception:
                logger.exception("slirp_watcher: exception launching slirp4netns")
            finally:
                self._slirp_process = None
                try:
                    os.close(pipe_w)
                except OSError:
                    pass
            return

    @staticmethod
    def _setup_port_forwarding(api_socket: str, ports_spec: str) -> None:
        """Forward host ports to sandbox via slirp4netns API."""
        if not ports_spec:
            return
        for _ in range(50):
            if os.path.exists(api_socket) and _is_socket(api_socket):
                break
            time.sleep(0.1)
        else:
            logger.error("Port forwarding: API socket not ready")
            return
        for spec in ports_spec.split():
            try:
                proto, port_str = spec.split(":", 1)
                port = int(port_str)
            except ValueError:
                continue
            try:
                s = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
                s.connect(api_socket)
                cmd = json.dumps(
                    {
                        "execute": "add_hostfwd",
                        "arguments": {
                            "proto": proto,
                            "host_addr": "127.0.0.1",
                            "host_port": port,
                            "guest_addr": "10.0.2.100",
                            "guest_port": port,
                        },
                    }
                )
                s.sendall(cmd.encode() + b"\0")
                s.recv(4096)
                s.close()
            except Exception:
                pass

    def get_launch_params_for_python_sb(
        self,
        all_rules: AllRules,
        log_level: int,
        token: str,
        init_fn: str,
        pipe_path: Path,
        temp: Path,
    ) -> dict[str, Any]:
        """Return process_config, pass_fds, on_launched for python_sb launch path.

        When socket rules exist, injects netfilter_rules and wait_network so the
        child runs _wait_network_ready() and slirp4netns is started via on_launched.
        """
        port = self.port
        use_net_filter = self._use_network_filtering(all_rules)
        netfilter_rules: tuple[str, ...] = ()
        if use_net_filter:
            netfilter_rules = self._build_netfilter_rules(all_rules, port)
            if not which_command("slirp4netns"):
                logger.error(
                    "slirp4netns not found; required for bwrap network filtering. "
                    "Install slirp4netns or use bwrap.share-net=yes to keep host network."
                )
                raise SystemExit(1)

        process_config = DaemonParameters(
            all_rules=all_rules,
            log_level=log_level,
            log_format=get_log_formatter(),
            use_rich_handler=use_rich_handler(),
            token=token,
            port=port,
            init_fn=init_fn,
            netfilter_rules=netfilter_rules,
            slirp_ready_fd=None,
            wait_network=use_net_filter,
        )
        result: dict[str, Any] = {"process_config": process_config}
        if use_net_filter:
            self._slirp_shutdown_event.clear()
            slirp_pipe_r, slirp_pipe_w = os.pipe()
            fd, api_socket = tempfile.mkstemp()
            os.close(fd)
            os.unlink(api_socket)
            self._slirp_api_socket = api_socket
            result["process_config"] = process_config._replace(
                slirp_ready_fd=slirp_pipe_r
            )

            def on_launched(pid: int) -> None:
                threading.Thread(
                    target=self._slirp_watcher,
                    args=(slirp_pipe_w, api_socket, pid),
                    daemon=True,
                ).start()
                ports_spec = self._extract_port_forwards(all_rules)
                if ports_spec:
                    threading.Thread(
                        target=self._setup_port_forwarding,
                        args=(api_socket, ports_spec),
                        daemon=True,
                    ).start()

            result["pass_fds"] = (slirp_pipe_r,)
            result["on_launched"] = on_launched
        return result

    @override
    def parse_rules(
        self,
        rules: ConfigLines,
        errors: list[ErrorMsg],
    ) -> tuple[ImmutableDict[str, Any], ConfigLines]:
        """Parse config lines: bwrap.* → os_sandbox_params, rest passed through."""
        bwrap_params: dict[str, str] = {}
        other_rules: ConfigLines = []

        for rule in rules:
            if rule.rule.startswith("bwrap."):
                param = rule.rule[len("bwrap.") :]
                key, _, val = param.partition("=")
                bwrap_params[key] = val
            else:
                other_rules.append(rule)
        return ImmutableDict(bwrap_params), other_rules

    @override
    def update_rules_and_activate(
        self,
        *,
        all_rules: AllRules,
        envs: Envs,
        temp: Path,
    ) -> AllRules:
        """No rule replacement for bwrap; return rules unchanged."""
        return all_rules

    @property
    @override
    def base_url(self) -> str:
        """Localhost; with --unshare-net slirp4netns forwards host 127.0.0.1 to guest."""
        return "http://localhost:{PORT}"

    def _bwrap_args(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> Args:
        """Build bwrap command arguments from template and rules."""
        bwrap_cmd = which_command("bwrap")
        if bwrap_cmd is None:
            logger.error("bwrap not found. Install it with:")
            logger.error(suggest_package_installation("bubblewrap"))
            sys.exit(1)

        args: Args = [str(bwrap_cmd)]

        # Load template (pysandboxes.templates)
        template_path: Path = (
            cast(
                Path,
                importlib.resources.files("pysandboxes"),  # type: ignore[attr-defined]
            )
            / "templates"
            / "bwrap.template"
        ).resolve()
        template_lines = remove_comments(template_path.read_text().splitlines())
        template_lines = substitute_env_vars(template_lines, envs)
        for line in template_lines:
            args.extend(shlex.split(line))

        # Profile env vars so the child sees TERM, My_ENV, etc. (template uses --clearenv)
        for k, v in all_rules.envs.items():
            args.extend(["--setenv", k, str(v)])

        # Network: share host net by default; use unshare-net + slirp + iptables when socket rules exist
        use_net_filter = self._use_network_filtering(all_rules)
        if use_net_filter:
            args.extend(["--unshare-net"])
        else:
            args.extend(["--share-net"])
        # Optional bwrap.* params (skip share-net/unshare-net to avoid overriding)
        for k, v in all_rules.os_sandbox_params.items():
            if k in ("share-net", "unshare-net"):
                continue
            if v:
                args.append(f"--{k}={v}")
            else:
                args.append(f"--{k}")

        # Minimal binds: /usr, /etc, /run (for resolv.conf when it points into /run)
        args.extend(["--ro-bind", "/usr", "/usr"])
        args.extend(["--ro-bind", "/etc", "/etc"])
        if Path("/run").is_dir():
            args.extend(["--ro-bind", "/run", "/run"])
        for lib_dir in ("/lib", "/lib64"):
            if Path(lib_dir).is_dir():
                args.extend(["--ro-bind", lib_dir, lib_dir])

        # Python executable and libraries: bind venv/prefix and resolved binary
        # so that symlinks like .venv/bin/python3 -> python -> /opt/conda/bin/python3.13 work
        bin_paths: set[Path] = set()
        follow_links_executable(Path(sys.executable), bin_paths)
        for p in bin_paths:
            args.extend(["--ro-bind", str(p), str(p)])
        resolved_exe = Path(sys.executable).resolve(strict=True)
        if resolved_exe not in bin_paths and not any(
            p in resolved_exe.parents for p in bin_paths
        ):
            args.extend(["--ro-bind", str(resolved_exe), str(resolved_exe)])
        for sp in sys.path:
            if sp and os.path.isdir(sp):
                args.extend(["--ro-bind", sp, sp])
        if hasattr(site, "getsitepackages"):
            for sp in site.getsitepackages():
                if sp and os.path.isdir(sp):
                    args.extend(["--ro-bind", sp, sp])

        # File rules: apply ro-bind first, then bind so writable mounts override
        for rule in all_rules.file_rules:
            if isinstance(rule, BindRule) and not rule.write:
                dest = rule.dest if rule.dest is not None else rule.source
                args.extend(["--ro-bind", rule.source, dest])
        for rule in all_rules.file_rules:
            if isinstance(rule, BindRule) and rule.write:
                dest = rule.dest if rule.dest is not None else rule.source
                args.extend(["--bind", rule.source, dest])

        # Temp dir so child can read the config pipe
        temp_str = str(temp)
        if temp_str:
            args.extend(["--bind", temp_str, temp_str])

        # Overlay ignore paths (e.g. .env) so they are not visible in the sandbox
        ignore_rules = [r for r in all_rules.file_rules if isinstance(r, IgnoreRule)]
        current_dir = os.getcwd()
        ignore_paths = _resolve_ignore_paths(current_dir, ignore_rules)
        for i, rel_path in enumerate(ignore_paths):
            full_host = os.path.normpath(os.path.join(current_dir, rel_path))
            if not os.path.exists(full_host):
                continue
            try:
                if os.path.isfile(full_host):
                    placeholder = temp / f"pysb_ignore_{i}"
                    placeholder.touch()
                else:
                    placeholder = temp / f"pysb_ignore_{i}"
                    placeholder.mkdir(exist_ok=True)
                args.extend(["--bind", str(placeholder), full_host])
            except OSError as e:
                logger.debug(
                    "Could not create overlay for ignore path %s: %s", full_host, e
                )

        return args

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Build full command: bwrap [args] -- python -m pysandboxes.remote.main_sandbox ..."""
        inner_cmd, extra_env = super().subprocess_cmd(
            all_rules, envs, pipe_path, temp=temp
        )
        bwrap_args = self._bwrap_args(
            all_rules=all_rules, envs=dict(envs), pipe_path=pipe_path, temp=temp
        )
        bwrap_args.append("--")
        bwrap_args.extend(inner_cmd)
        return bwrap_args, extra_env

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
        """Start bwrap subprocess; when socket rules exist, use slirp4netns + netfilter."""
        self._is_started = False
        self._accept_incoming = False
        init_fn_ref = ""
        if init_fn:
            module, func_ref = get_callable_info(init_fn)
            init_fn_ref = f"{module}:{func_ref}"

        use_net_filter = self._use_network_filtering(all_rules)
        netfilter_rules: tuple[str, ...] = ()
        if use_net_filter:
            netfilter_rules = self._build_netfilter_rules(all_rules, port)
            if not which_command("slirp4netns"):
                logger.error(
                    "slirp4netns not found; required for bwrap network filtering. "
                    "Install slirp4netns or use bwrap.share-net=yes to keep host network."
                )
                raise SystemExit(1)

        process_config = DaemonParameters(
            all_rules=all_rules,
            log_level=log_level,
            log_format=get_log_formatter(),
            use_rich_handler=use_rich_handler(),
            token=self._token,
            port=port,
            init_fn=init_fn_ref,
            netfilter_rules=netfilter_rules,
            slirp_ready_fd=None,
            wait_network=use_net_filter,
        )

        env: Environ = {**os.environ, **extra_envs}

        launch_kwargs: dict[str, Any] = dict(
            cmd=args + ["--_named-pipe", str(pipe_path)],
            pipe_path=pipe_path,
            envs=Envs(env),
            process_config=process_config,
        )

        if use_net_filter:
            self._slirp_shutdown_event.clear()
            slirp_pipe_r, slirp_pipe_w = os.pipe()
            fd, api_socket = tempfile.mkstemp()
            os.close(fd)
            os.unlink(api_socket)
            self._slirp_api_socket = api_socket
            process_config = process_config._replace(slirp_ready_fd=slirp_pipe_r)
            launch_kwargs["process_config"] = process_config

            def on_launched(pid: int) -> None:
                threading.Thread(
                    target=self._slirp_watcher,
                    args=(slirp_pipe_w, api_socket, pid),
                    daemon=True,
                ).start()
                ports_spec = self._extract_port_forwards(all_rules)
                if ports_spec:
                    threading.Thread(
                        target=self._setup_port_forwarding,
                        args=(api_socket, ports_spec),
                        daemon=True,
                    ).start()

            launch_kwargs["pass_fds"] = (slirp_pipe_r,)
            launch_kwargs["on_launched"] = on_launched

        logger.debug(
            "Launch process: %s",
            " ".join((repr(c) if " " in c else c for c in launch_kwargs["cmd"])),
        )
        self._process = await launch_sandbox(**launch_kwargs)
        ping_url = f"http://127.0.0.1:{port}/ping"
        logger.info(
            "Subprocess launched (pid=%s), pinging %s",
            self._process.pid,
            ping_url,
        )
        try:
            await self._on_process_started()
        except Exception:
            raise
        logger.info("Pinging subprocess daemon at %s", ping_url)
        gc.collect()
        connector = aiohttp.TCPConnector(family=socket_mod.AF_INET)
        async with aiohttp.ClientSession(connector=connector) as session:
            count_loop = 0
            while True:
                try:
                    count_loop += 1
                    if count_loop > LOOP_FOR_PING:
                        logger.error(
                            "Is not possible to connect to the sandbox daemon (%s)",
                            ping_url,
                        )
                        raise SystemExit(-1)
                    async with session.get(
                        ping_url,
                        timeout=ClientTimeout(total=TIMEOUT_FOR_PING),
                    ) as response:
                        if response.status == 200:
                            break
                        raise RuntimeError(
                            f"Unexpected status {response.status} from {ping_url}"
                        )
                except TimeoutError:
                    if count_loop % 15 == 0:
                        logger.info(
                            "Ping attempt %d/%d: timeout (subprocess not ready yet?)",
                            count_loop,
                            LOOP_FOR_PING,
                        )
                except (ClientConnectorError, ServerDisconnectedError):
                    if count_loop % 15 == 0:
                        logger.info(
                            "Ping attempt %d/%d: connection failed",
                            count_loop,
                            LOOP_FOR_PING,
                        )
                await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)
        await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)
        logger.info("Subprocess daemon is up and running at %s", ping_url)
        self._is_started = True
        self._accept_incoming = True

    async def _stop(self, max_pending: int) -> None:
        """Stop daemon and slirp4netns when network filtering was used."""
        self._slirp_shutdown_event.set()
        proc = self._slirp_process
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except OSError:
                    pass
            self._slirp_process = None
        await super()._stop(max_pending)
