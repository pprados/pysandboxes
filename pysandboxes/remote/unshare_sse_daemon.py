# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Unshare-based daemon for OS-level sandboxing.

This module implements a unshare-based sandbox daemon that uses
Linux namespaces directly via the `unshare` command, `slirp4netns`
for networking, and standard Linux tools (mount, iptables) for isolation.

Unlike the previous implementation, this daemon directly invokes `unshare`
to launch `unshare_setup.py`, eliminating the intermediate `unshare_launcher`
process. The daemon itself manages slirp4netns networking and port forwarding.
"""

import asyncio
import fnmatch
import gc
import logging
import os
import pickle
import random
import site
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from asyncio import CancelledError, Task
from asyncio.subprocess import Process
from ipaddress import IPv4Address, IPv4Network
from pathlib import Path
from typing import Any, cast

import aiohttp
from aiohttp import ClientConnectorError, ClientOSError, ClientTimeout, ServerDisconnectedError

from ..all_rules import AllRules
from ..e import SandBoxError
from ..guard_files import FSExposeRule, IgnoreRule
from ..guard_socket import Action, Direction, SocketRule
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg, pysandboxes_logger
from ..netfilter import rule_to_netfilter
from ..override_compat import override
from ..private_loop import sandbox_loop
from ..sb_types import Args, ConfigLine, ConfigLines
from ..tools import (
    Environ,
    SyncOrAsyncFunc,
    follow_links_executable,
    get_callable_info,
    remove_comments,
    substitute_env_vars,
)
from .client_subprocess_sse_daemon import (
    DEBUG_LAUNCH,
    BaseSubProcessDaemon,
    find_free_port,
    get_log_formatter,
    use_rich_handler,
)
from .daemon_parameters import DaemonParameters
from .parameters import (
    INTERVAL_FOR_PING_DAEMON,
    LOOP_FOR_PING,
    MAX_CONNECT_RETRY,
    RETRY_BASE_DELAY,
    RETRY_FACTOR,
    RETRY_MAX_ATTEMPTS,
    RETRY_MAX_DELAY,
    RETRY_RESET_DELAY,
    TIMEOUT_FOR_PING,
)
from .slirp4netns_common import (
    SLIRP_DNS,
    SLIRP_WATCHER_TIMEOUT,
)
from .slirp4netns_common import (
    extract_port_forwards as slirp_extract_port_forwards,
)
from .slirp4netns_common import (
    make_slirp_temp_files as slirp_make_temp_files,
)
from .slirp4netns_common import (
    remove_slirp_temp_files as slirp_remove_temp_files,
)
from .slirp4netns_common import (
    run_slirp_watcher as slirp_run_watcher,
)
from .slirp4netns_common import (
    setup_port_forwarding as slirp_setup_port_forwarding,
)
from .tools import (
    SSE_READ_BUFSIZE,
    get_upstream_dns,
    is_transient_connection_error,
    unshare_user_namespace_available,
    which_command,
)
from .unshare_setup import UnshareSetupConfig

logger = logging.getLogger(__name__)


# TODO: handle slirp4netns crash


def _resolve_ignore_paths(
    current_dir: str,
    ignore_rules: list[IgnoreRule],
) -> list[str]:
    """Resolve ignore rules to concrete paths under current_dir.

    Walks the directory tree and collects paths whose basename matches any
    ignore pattern (same semantics as guard_files). Returns paths relative
    to current_dir.
    """
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


class UnshareSSEDaemon(BaseSubProcessDaemon):
    """Unshare-based sandbox daemon with integrated namespace management.

    Directly manages the `unshare` subprocess and `slirp4netns` networking,
    eliminating the need for the intermediate `unshare_launcher` process.

    Process chain: daemon -> unshare -> unshare_setup -> main_sandbox
    """

    __slots__ = (
        "_process",
        "_watchdog",
        "_attempts",
        "_base_delay",
        "_factor",
        "_max_delay",
        "_max_attempts",
        "_reset_delay",
        "_last_reset",
        "_python_args",
        "restart",
        "_chroot_dirs",
        "_slirp_pid_file",
        "_slirp_api_socket",
        "_slirp_pipe_r",
        "_slirp_pipe_w",
        "_slirp_pid_file_for_watcher",
        "_slirp_api_socket_for_watcher",
        "_ports_spec",
        "_slirp_process_holder",
        "_slirp_shutdown_event",
    )

    @classmethod
    @override
    def unavailable_reason(cls) -> str | None:
        if unshare_user_namespace_available():
            return None
        return "unshare/slirp4netns missing or user namespaces not permitted"

    def __init__(
        self,
        token: str,
        *,
        host: str = "localhost",
        python_args: list[str] | None = None,
        max_connect_retry: int = MAX_CONNECT_RETRY,
        max_attempts: int = RETRY_MAX_ATTEMPTS,
        base_delay: float = RETRY_BASE_DELAY,
        factor: float = RETRY_FACTOR,
        max_delay: float = RETRY_MAX_DELAY,
        reset_delay: float = RETRY_RESET_DELAY,
    ) -> None:
        super().__init__(token, max_connect_retry=max_connect_retry)
        self._python_args = python_args or []
        self._process: Process | None = None
        self._watchdog: Task | None = None
        self._attempts = 0
        self._base_delay = base_delay
        self._factor = factor
        self._max_delay = max_delay
        self._max_attempts = max_attempts
        self._reset_delay = reset_delay
        self._last_reset = time.time()
        self._is_started = False
        self.restart = 0
        self._chroot_dirs: list[str] = []
        self._slirp_pid_file: str | None = None
        self._slirp_api_socket: str | None = None
        self._slirp_process_holder: list[subprocess.Popen[bytes] | None] = [None]
        self._slirp_shutdown_event: threading.Event = threading.Event()

    @override
    def parse_rules(
        self,
        rules: ConfigLines,
        errors: list[ErrorMsg],
    ) -> tuple[ImmutableDict[str, Any], ConfigLines]:
        unshare_params: dict[str, str] = {}
        ignore_rules: ConfigLines = []

        for rule in rules:
            if rule.rule.startswith("unshare."):
                param = rule.rule[len("unshare.") :]
                key, _, val = param.partition("=")
                unshare_params[key] = val
            else:
                ignore_rules.append(rule)
        return ImmutableDict(unshare_params), ignore_rules

    # -- Private helpers for building the unshare command --

    def _build_daemon_cmd(self) -> Args:
        """Build the base command for the sandbox daemon process (main_sandbox)."""
        from . import main_sandbox

        cmd: Args = [sys.executable, "-u"]
        if sys.flags.optimize:
            cmd.append("-" + "O" * sys.flags.optimize)
        cmd.extend(self._python_args)
        cmd.extend(["-m", main_sandbox.__name__])
        return cmd

    def _make_chroot_dir(self) -> str:
        """Reserve the chroot root for one launch, and remember it for shutdown.

        ``unshare_setup`` execs into the sandbox, so it can never remove the directory
        it chroots into; it is created here instead. Each relaunch gets its own, so
        they are kept as a list rather than a single field.
        """
        chroot_dir = tempfile.mkdtemp()
        self._chroot_dirs.append(chroot_dir)
        return chroot_dir

    def _remove_chroot_dirs(self) -> None:
        """Remove the chroot roots, now that the namespaces holding their tmpfs are gone."""
        for chroot_dir in self._chroot_dirs:
            try:
                os.rmdir(chroot_dir)
            except OSError as e:
                logger.debug("cannot remove chroot root %s: %s", chroot_dir, e)
        self._chroot_dirs.clear()

    def _prepare_unshare_config(
        self,
        all_rules: AllRules,
        pipe_path: Path,
        chroot_dir: str,
    ) -> tuple[UnshareSetupConfig, list[IPv4Address]]:
        """Prepare UnshareSetupConfig (DNS, mounts, netfilter)."""
        # Verify unshare availability
        if not which_command("unshare"):
            logger.error("unshare not found.")
            sys.exit(1)

        if not which_command("iptables"):
            logger.error("iptables not found.")
            sys.exit(1)

        # Check unprivileged user namespaces
        try:
            with open("/proc/sys/kernel/unprivileged_userns_clone", "r") as f:
                if f.read().strip() != "1":
                    raise RuntimeError("kernel.unprivileged_userns_clone must be 1")
        except FileNotFoundError:
            pass

        # DNS servers: use slirp4netns built-in DNS so resolution is routable
        # inside the namespace via tap0; upstream DNS from the host may be unreachable
        # when the daemon runs inside a container (e.g. podman).
        slirp_dns = IPv4Address(SLIRP_DNS)
        dns_servers = [ip for ip in get_upstream_dns() if isinstance(ip, IPv4Address)]
        if not dns_servers or os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
            dns_servers = [slirp_dns]
        else:
            dns_servers = [slirp_dns] + [ip for ip in dns_servers if ip != slirp_dns][:1]
        net_filter4 = rule_to_netfilter(all_rules.socket_rules, dns_servers, is_ipv6=False)

        # Build hosts from OUT ALLOW rules so the sandbox resolves hostnames to the
        # same IPs that iptables allows (avoids mismatch when sandbox uses slirp DNS).
        hosts_entries: set[tuple[str, str]] = set()
        for socket_rule in all_rules.socket_rules:
            if socket_rule.action != Action.ALLOW or Direction.OUT not in socket_rule.directions:
                continue
            net = socket_rule.mask.network
            if not isinstance(net, IPv4Network) or net.prefixlen != 32:
                continue
            try:
                value = socket_rule.config.rule[len("net=") :]
                parts = value.split("|", 4)
                if len(parts) < 3:
                    continue
                network_str = parts[2].strip()
                if "/" in network_str or network_str.replace(".", "").isdigit():
                    continue
                hosts_entries.add((str(net.network_address), network_str))
            except (IndexError, AttributeError):
                continue
        hosts_list = [f"{ip} {hostname}" for (ip, hostname) in sorted(hosts_entries)]

        # Build mounts
        mounts: set[tuple[str, str, bool]] = set()
        for p in ["/bin", "/usr", "/lib", "/lib64", "/etc"]:
            mounts.add((p, p, False))
        mounts.add((str(pipe_path), str(pipe_path), True))

        python_paths = [sys.executable] + sys.path
        if hasattr(site, "getsitepackages"):
            python_paths += site.getsitepackages()
        for p in python_paths:
            if p and os.path.exists(p):
                mounts.add((p, p, False))

        # Mounting sys.executable is not enough to be able to run it. A venv reaches the
        # interpreter through a chain of symlinks, and a bind mount resolves its target:
        # the real binary lands where the chain ends, not at `.venv/bin/python`, which
        # stays dangling inside the namespace -- `setpriv: failed to execute .../python:
        # No such file or directory`. Mount every directory the chain names instead, as
        # bwrap and firejail already do.
        for link_path in follow_links_executable(Path(sys.executable), set()):
            mounts.add((str(link_path), str(link_path), False))

        for rule in all_rules.file_rules:
            if isinstance(rule, FSExposeRule):
                mounts.add((rule.path, rule.path, rule.write))
            elif isinstance(rule, IgnoreRule):
                pass  # Handled via ignore_paths overlay in unshare_setup

        current_dir = os.getcwd()
        ignore_paths = _resolve_ignore_paths(
            current_dir,
            [r for r in all_rules.file_rules if isinstance(r, IgnoreRule)],
        )

        config = UnshareSetupConfig(
            dns_servers=[str(ip) for ip in dns_servers],
            hosts=hosts_list,
            mounts_ro=[(m[0], m[1]) for m in mounts if not m[2]],
            mounts_rw=[(m[0], m[1]) for m in mounts if m[2]],
            named_pipe=str(pipe_path),
            netfilter_rules=net_filter4,
            current_dir=current_dir,
            ignore_paths=ignore_paths,
            # The setup stage runs with the host environment, on purpose; this is what
            # it narrows down to before exec'ing into the sandbox.
            sandbox_envs={k: str(v) if v is not None else "" for k, v in dict(all_rules.envs).items()},
            chroot_dir=chroot_dir,
        )
        return config, dns_servers

    def _get_unshare_flags(self, all_rules: AllRules, envs: Environ) -> list[str]:
        """Get unshare flags from template and custom params."""
        # Python 3.10+ only
        import importlib.resources

        template_path: Path = (
            cast(
                Path,
                importlib.resources.files(".".join(__name__.rsplit(".", maxsplit=1)[:-1])),
            )
            / ".."
            / "templates"
            / "unshare.template"
        ).resolve()

        template_conf = remove_comments(template_path.read_text().splitlines())
        envs["UID"] = str(os.getuid())
        envs["GID"] = str(os.getgid())
        template_conf = substitute_env_vars(template_conf, envs)

        flags: list[str] = []
        for line in template_conf:
            flags.extend(line.split())
        for k, v in all_rules.os_sandbox_params.items():
            if v:
                flags.append(f"--{k}={v}")
            else:
                flags.append(f"--{k}")
        return flags

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Build command line for python_sb.py one-shot execution.

        Sets up slirp4netns management (watcher thread, port forwarding thread)
        and returns the direct unshare command. The slirp readiness pipe fd is
        passed to the child via launch_sandbox's extra_preexec_fn and pass_fds.
        """
        # Prepare UnshareSetupConfig
        config, _ = self._prepare_unshare_config(all_rules, pipe_path, self._make_chroot_dir())

        # Write config via FIFO (or file in debug mode). Always pass a path under
        # temp so the unshare child can read it (e.g. under /tmp); with Docker the
        # child may not have access to /app when using unshare -r.
        if DEBUG_LAUNCH:
            debug_tmp = Path("tmp")
            debug_tmp.mkdir(parents=True, exist_ok=True)
            config_file = debug_tmp / "unshare_config.json"
            logger.debug("DEBUG_LAUNCH: config file %s", config_file.resolve())
        else:
            config_file = temp / "unshare_config.json"
            if config_file.exists():
                config_file.unlink()
            os.mkfifo(config_file)

        def publish_config() -> None:
            config_file.write_text(config.to_json())
            if not DEBUG_LAUNCH:
                try:
                    config_file.unlink(missing_ok=True)
                except Exception:
                    # Best effort: the FIFO has already been read by the child,
                    # so a failed unlink leaves a stale entry in a temporary
                    # directory, never an unguarded sandbox.
                    pass

        threading.Thread(target=publish_config, daemon=True).start()

        # Build unshare flags from template
        unshare_flags = self._get_unshare_flags(all_rules, dict(envs))

        # Build command: unshare <flags> -- python -m unshare_setup <config> -- <daemon_cmd>
        args: Args = [
            "unshare",
            *unshare_flags,
            "--",
            # "/usr/bin/bash" # FIXME
            sys.executable,
            "-m",
            "pysandboxes.remote.unshare_setup",
            str(config_file.resolve()),
            "--",
        ]

        daemon_cmd = self._build_daemon_cmd()
        args.extend(daemon_cmd)  # FIXME

        # Create slirp4netns temp files (shared helper)
        pid_file, api_socket = slirp_make_temp_files()
        self._slirp_pid_file = pid_file
        self._slirp_api_socket = api_socket

        # Create readiness pipe for slirp4netns -> unshare_setup (fd 3)
        slirp_pipe_r, slirp_pipe_w = os.pipe()

        # Store pipe info for launch_sandbox preexec_fn and pass_fds
        self._slirp_pipe_r = slirp_pipe_r
        self._slirp_pipe_w = slirp_pipe_w
        self._slirp_pid_file_for_watcher = pid_file
        self._slirp_api_socket_for_watcher = api_socket

        # unshare_setup.py runs BEFORE the sandbox is built (it creates the
        # chroot, configures networking, etc.). It needs a full working
        # environment (PATH for mount/ip/iptables, PYTHONPATH for module
        # imports, HOME, LANG, etc.). When learn=False, python_sb.py strips
        # os.environ — but for unshare mode, isolation comes from the
        # namespaces + chroot, NOT from env stripping. So we re-inject the
        # full host environment here.
        # Ensure the unshare child can import pysandboxes: in Docker the
        # editable install (.pth) may not be visible in the new mount namespace,
        # so set PYTHONPATH to the project root explicitly.
        project_root = os.getcwd()
        existing_pp = os.environ.get("PYTHONPATH", "")
        pythonpath = f"{project_root}:{existing_pp}" if existing_pp else project_root
        extra_envs = {
            "PID_FILE": pid_file,
            "SLIRP_READY_FD": str(slirp_pipe_r),
            "PYTHONPATH": pythonpath,
        }

        # Extract ports for forwarding
        self._ports_spec = slirp_extract_port_forwards(all_rules, self.port)

        return args, extra_envs

    @override
    def get_launch_extras(self) -> tuple[Any, tuple[int, ...]]:
        """Return (extra_preexec_fn, pass_fds) for launch_sandbox.

        Must be called after subprocess_cmd(). Returns the preexec function
        and fds that launch_sandbox needs to pass to the child process.
        """
        slirp_pipe_r = self._slirp_pipe_r

        def extra_preexec_fn() -> None:
            pass  # fd is passed via pass_fds; no dup2 needed

        return extra_preexec_fn, (slirp_pipe_r,)

    @override
    def on_process_launched(self, process_pid: int) -> None:
        """Called after launch_sandbox to start slirp4netns management.

        Args:
            process_pid: PID of the launched unshare process.
        """
        # Close read end in parent (child has its copy)
        try:
            os.close(self._slirp_pipe_r)
        except OSError:
            pass

        # Write PID for slirp4netns watcher
        Path(self._slirp_pid_file_for_watcher).write_text(str(process_pid))

        # Start slirp4netns watcher (shared helper)
        logger.debug("start slirp4netns watcher...")
        threading.Thread(
            target=slirp_run_watcher,
            args=(
                self._slirp_shutdown_event,
                self._slirp_pipe_w,
                self._slirp_api_socket_for_watcher,
            ),
            kwargs={
                "pid_file": self._slirp_pid_file_for_watcher,
                "process_holder": self._slirp_process_holder,
                "timeout": SLIRP_WATCHER_TIMEOUT,
            },
            daemon=True,
        ).start()

        # Start port forwarding
        logger.debug("start port forwarning watcher...")
        if self._ports_spec:
            threading.Thread(
                target=slirp_setup_port_forwarding,
                args=(self._slirp_api_socket_for_watcher, self._ports_spec),
                daemon=True,
            ).start()

    def _kill_slirp(self) -> None:
        """Terminate the slirp4netns process if it is still running."""
        self._slirp_shutdown_event.set()
        proc = self._slirp_process_holder[0] if self._slirp_process_holder else None
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                # Teardown: the process is already gone, refuses to die, or
                # outlives the timeout. Nothing here can recover it, and the
                # caller is shutting down, so carry on to remove the socket
                # and the pid file below.
                pass
            self._slirp_process_holder[0] = None
        slirp_remove_temp_files(self._slirp_pid_file, self._slirp_api_socket)
        self._slirp_pid_file = None
        self._slirp_api_socket = None

    @override
    async def _shutdown(self, graceful_shutdown: bool = True) -> None:
        """Shutdown the sandbox and kill slirp4netns."""
        self._slirp_shutdown_event.set()
        try:
            await super()._shutdown(graceful_shutdown)
        finally:
            await asyncio.to_thread(self._kill_slirp)
            await asyncio.to_thread(self._remove_chroot_dirs)

    # -- Daemon lifecycle --

    @override
    async def _start(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        self.restart = 0
        self.port = find_free_port() if all_rules.port == -1 else all_rules.port
        await self._launch(
            all_rules,
            envs=envs,
            log_level=log_level,
            init_fn=init_fn,
            first=True,
        )
        self._watchdog = asyncio.create_task(
            self._watchdog_loop(
                all_rules,
                envs=envs,
                log_level=log_level,
                init_fn=init_fn,
            ),
            name="ControlDaemon",
        )

    async def _watchdog_loop(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
    ) -> None:
        """Monitor subprocess and restart on failure."""
        errorlevel = -1
        if self._process is None:
            return
        try:
            self._attempts = 0
            while errorlevel != 0:
                errorlevel = await self._process.wait()
                if not self._accept_incoming:
                    break
                if errorlevel != 0:
                    logger.info("watchdog: subprocess exited with %s", errorlevel)
                    if time.time() - self._last_reset > self._reset_delay:
                        self._attempts = 0
                    self._attempts += 1
                    if self._attempts > self._max_attempts:
                        logger.error("Too many daemon shutdowns")
                        os._exit(-2)
                    current_base_backoff: float = min(
                        self._max_delay,
                        self._base_delay * (self._factor ** (self._attempts - 1)),
                    )
                    wait_time: float = random.uniform(current_base_backoff * 0.9, current_base_backoff)
                    logger.debug("watchdog sleep %i", wait_time)
                    await asyncio.sleep(wait_time)
                    self._last_reset = time.time()
                    await self._launch(
                        all_rules,
                        envs=envs,
                        log_level=log_level,
                        init_fn=init_fn,
                    )
        except CancelledError:
            pass

    async def _launch(
        self,
        all_rules: AllRules,
        *,
        envs: Environ,
        log_level: int,
        init_fn: SyncOrAsyncFunc | None,
        first: bool = False,
    ) -> None:
        """Launch the unshare subprocess with integrated namespace management."""
        with tempfile.TemporaryDirectory() as tmpdir:
            temp = Path(tmpdir)
            pipe_path = temp / f"_{uuid.uuid4().hex}"
            pipe_path.unlink(missing_ok=True)

            # Add socket rule for daemon port communication
            from ..guard_socket import parse_rules as socket_parse_rules

            socket_rules: list[SocketRule] = list(all_rules.socket_rules)
            _new_socket_rules, *_ = socket_parse_rules([ConfigLine(f"net=ALLOW|TCP|*|{self.port}|IN", Path(), 0)], [])
            socket_rules.extend(_new_socket_rules)

            from pysandboxes.guard_socket import SocketRules

            all_rules = all_rules._replace(socket_rules=SocketRules(socket_rules))

            # Prepare UnshareSetupConfig
            config, dns_servers = self._prepare_unshare_config(all_rules, pipe_path, self._make_chroot_dir())

            # Write UnshareSetupConfig via FIFO (or file in debug mode)
            if DEBUG_LAUNCH:
                debug_tmp = Path("tmp")
                debug_tmp.mkdir(parents=True, exist_ok=True)
                config_file = debug_tmp / "unshare_config.json"
                logger.debug("DEBUG_LAUNCH: config file %s", config_file.resolve())
            else:
                config_file = temp / "unshare_config.json"
                if config_file.exists():
                    config_file.unlink()
                os.mkfifo(config_file)

            def publish_config() -> None:
                config_file.write_text(config.to_json())
                if not DEBUG_LAUNCH:
                    try:
                        config_file.unlink(missing_ok=True)
                    except Exception:
                        # Best effort: see the comment on the other
                        # publish_config above -- a stale FIFO, nothing more.
                        pass

            threading.Thread(target=publish_config, daemon=True).start()

            # Build unshare flags from template
            unshare_flags = self._get_unshare_flags(all_rules, dict(envs))

            # Build daemon command (python -m main_sandbox)
            daemon_cmd = self._build_daemon_cmd()

            # Build full command:
            # unshare <flags> -- python -m unshare_setup <config> -- <daemon> --_named-pipe <pipe>
            cmd: Args = [
                "unshare",
                *unshare_flags,
                "--",
                sys.executable,
                "-m",
                "pysandboxes.remote.unshare_setup",
                str(config_file.resolve()),
                "--",
                *daemon_cmd,
                "--_named-pipe",
                str(pipe_path),
            ]

            # Create slirp4netns temp files (shared helper)
            pid_file, api_socket = slirp_make_temp_files()
            self._slirp_pid_file = pid_file
            self._slirp_api_socket = api_socket

            # Create readiness pipe: slirp4netns writes to pipe_w (fd 4),
            # unshare_setup reads from pipe_r (fd 3)
            slirp_pipe_r, slirp_pipe_w = os.pipe()

            # Build DaemonParameters for main_sandbox
            self._is_started = False
            self._accept_incoming = False
            if init_fn:
                module, init_function_reference = get_callable_info(init_fn)
                init_fn_ref = f"{module}:{init_function_reference}"
            else:
                init_fn_ref = ""

            process_config = DaemonParameters(
                all_rules=all_rules,
                log_level=log_level,
                log_format=get_log_formatter(),
                use_rich_handler=use_rich_handler(),
                token=self._token,
                port=self.port,
                init_fn=init_fn_ref,
            )

            # Build environment (PYTHONPATH so unshare child finds pysandboxes in Docker)
            env: Environ = {**os.environ}
            env["PID_FILE"] = pid_file
            project_root = os.getcwd()
            existing_pp = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = f"{project_root}:{existing_pp}" if existing_pp else project_root

            # Extract ports for forwarding
            ports_spec = slirp_extract_port_forwards(all_rules, self.port)

            # Create the DaemonParameters FIFO
            os.mkfifo(pipe_path)

            if DEBUG_LAUNCH:
                try:
                    debug_tmp = Path("tmp")
                    debug_tmp.mkdir(parents=True, exist_ok=True)
                    run_sh = debug_tmp / "run.sh"
                    run_sh.write_text(
                        "#!/bin/bash\n"
                        + cmd[0]
                        + " "
                        + " \\\n  ".join(repr(c) if " " in c else c for c in cmd[1:])
                        + "\n"
                    )
                    logger.debug("DEBUG_LAUNCH: wrote %s", run_sh.resolve())
                except Exception:
                    logger.debug("Cannot write run.sh")

            def preexec_fn() -> None:
                os.umask(0o006)

            # Pass slirp readiness fd via environment variable
            env["SLIRP_READY_FD"] = str(slirp_pipe_r)

            logger.debug("Start process: " + " ".join((repr(c) if " " in c else c for c in cmd)))

            # Launch unshare process
            @sandbox_loop
            async def _do_launch() -> Process:
                return await asyncio.create_subprocess_exec(
                    *cmd,
                    env=env,
                    preexec_fn=preexec_fn,
                    pass_fds=(slirp_pipe_r,),
                )

            self._process = await _do_launch()
            process = self._process
            assert process is not None
            logger.debug("_launch: process started pid=%s", process.pid)

            # Close read end in parent (child has its own copy via pass_fds)
            os.close(slirp_pipe_r)

            # Write unshare PID for slirp4netns to attach to the namespace
            assert process.pid is not None
            Path(pid_file).write_text(str(process.pid))
            logger.debug(
                "_launch: wrote pid %d to pidfile, starting slirp_watcher pipe_w=%d",
                process.pid,
                slirp_pipe_w,
            )

            # Start slirp4netns watcher thread (shared helper)
            threading.Thread(
                target=slirp_run_watcher,
                args=(
                    self._slirp_shutdown_event,
                    slirp_pipe_w,
                    api_socket,
                ),
                kwargs={
                    "pid_file": pid_file,
                    "process_holder": self._slirp_process_holder,
                    "timeout": SLIRP_WATCHER_TIMEOUT,
                },
                daemon=True,
            ).start()
            logger.debug("_launch: slirp_watcher thread started")

            # Write DaemonParameters to FIFO
            # This blocks until main_sandbox opens the FIFO for reading,
            # which happens after unshare_setup completes namespace configuration.
            gc.collect()
            with open(pipe_path, "wb") as fifo:
                # serialization only
                fifo.write(pickle.dumps(process_config))
                fifo.flush()
            pipe_path.unlink()

            # Start port forwarding
            if ports_spec:
                threading.Thread(
                    target=slirp_setup_port_forwarding,
                    args=(api_socket, ports_spec),
                    daemon=True,
                ).start()

            # Wait for daemon to be ready (ping loop)
            gc.collect()
            ping_url = self.base_url.replace("{PORT}", str(self.port)) + "/ping"
            logger.debug("Try to call %s", ping_url)
            async with aiohttp.ClientSession(read_bufsize=SSE_READ_BUFSIZE) as session:
                count_loop = 0
                while True:
                    try:
                        count_loop += 1
                        if count_loop > LOOP_FOR_PING:
                            logger.error(
                                "Cannot connect to the sandbox daemon (%s)",
                                ping_url,
                            )
                            # SandBoxError, not SystemExit: the latter is a BaseException,
                            # so the `except Exception` meant to clean up after a failed
                            # start never saw it, and what had been launched stayed alive.
                            raise SandBoxError(f"The unshare sandbox daemon never answered on {ping_url}.")
                        async with session.get(
                            ping_url,
                            timeout=ClientTimeout(total=TIMEOUT_FOR_PING),
                        ) as response:
                            if response.status == 200:
                                break
                            else:
                                raise RuntimeError(f"Unexpected status {response.status} from {ping_url}")
                    except TimeoutError:
                        pass
                    except (ClientConnectorError, ServerDisconnectedError):
                        pass
                    except ClientOSError as e:
                        if not is_transient_connection_error(e):
                            raise

                    await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)

            await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)
            logger.debug("Unshare Sandbox daemon is up and running")
            self._is_started = True
            self._accept_incoming = True

        if first:
            pysandboxes_logger.info("Unshare Daemon Sandbox started")
        else:
            pysandboxes_logger.warning("Unshare Daemon Sandbox re-started")
