# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""QEMU-based VM SSE daemon for PySandboxes.

Runs the sandbox inside a QEMU VM. Uses -net user + hostfwd for SSE.
Virtio-9p exposes file_rules root at /app (same strategy as bwrap) and
the run dir (named pipe for config) at /mnt/pysandbox_run. Guest runs
main_sandbox --_named-pipe to read config from the pipe.
"""

import asyncio
import gc
import logging
import os
import pickle
import platform
import site
import subprocess
import sys
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any

from ..all_rules import AllRules
from ..guard_files import BindRule
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg
from ..netfilter import rule_to_netfilter
from ..override_compat import override
from ..sb_types import Args, ConfigLines, Envs
from ..tools import Environ, follow_links_executable
from .parameters import (
    INTERVAL_FOR_PING_DAEMON,
    LOOP_FOR_PING,
    TIMEOUT_FOR_PING,
)

# VM boot + cloud-init can take 20–40s before main_sandbox listens; wait before pinging.
QEMU_BOOT_DELAY = 20.0
# Allow more ping attempts after boot (VM is slower than a subprocess).
QEMU_LOOP_FOR_PING = 200
from .client_subprocess_sse_daemon import (
    DaemonParameters,
    find_free_port,
    get_log_formatter,
    launch_sandbox,
    use_rich_handler,
)
from .qemu_image import ensure_image, get_default_image_path, is_kvm_available
from .qemu_setup import (
    GUEST_CONFIG_MOUNT,
    GUEST_RUN_MOUNT,
    prepare_guest_env,
)
from .tools import which_command
from .vm_sse_daemon import VMSSEDaemon

logger = logging.getLogger(__name__)


def _add_dir_follow_links(path: Path, out: set[Path]) -> None:
    """Add resolved directory to set (follow symlinks, firejail-style). Skip /usr/lib."""
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return
    if str(resolved).startswith("/usr/lib"):
        return
    dir_path = resolved if resolved.is_dir() else resolved.parent
    out.add(dir_path)


def _execution_dirs_mounts() -> list[tuple[str, Path, str]]:
    """Build 9p mounts for Python execution: sys.executable (follow symlinks), sys.path, site.getsitepackages().

    Same strategy as sse_firejail: follow links so venv/conda symlinks work. Guest path = host path
    so the guest Python finds the same libraries.
    """
    dirs: set[Path] = set()
    # sys.executable and its symlink chain (e.g. .venv/bin/python3 -> python -> /opt/conda/bin/python3.13)
    bin_paths: set[Path] = set()
    follow_links_executable(Path(sys.executable), bin_paths)
    for p in bin_paths:
        if p.is_file():
            dirs.add(p.parent.resolve(strict=True))
        else:
            _add_dir_follow_links(p, dirs)
    # sys.path and site.getsitepackages()
    for sp in sys.path:
        if sp and os.path.isdir(sp):
            _add_dir_follow_links(Path(sp), dirs)
    for sp in site.getsitepackages():
        if sp and os.path.isdir(sp):
            _add_dir_follow_links(Path(sp), dirs)
    # Deduplicate and build (tag, host_path, guest_path) with guest_path = host_path
    seen: set[Path] = set()
    mount_specs: list[tuple[str, Path, str]] = []
    for i, d in enumerate(sorted(dirs, key=lambda p: str(p))):
        d_res = d.resolve(strict=True)
        if not d_res.is_dir() or d_res in seen:
            continue
        seen.add(d_res)
        tag = f"pysb_exec_{i}"
        guest_path = str(d_res)
        mount_specs.append((tag, d_res, guest_path))
    return mount_specs


def _file_rules_mounts(
    all_rules: AllRules,
    temp: Path,
    pipe_path: Path,
    config_dir: Path | None = None,
) -> tuple[list[tuple[str, Path, str]], list[tuple[str, str]]]:
    """Build one 9p (tag, host_path, guest_path) per BindRule, run dir, optional config dir, and execution dirs.

    Returns (mount_specs, mount_list_for_iso) where mount_specs is used for -virtfs
    and mount_list_for_iso is [(tag, guest_path), ...] for the bootstrap script.
    When config_dir is set, it is mounted at GUEST_CONFIG_MOUNT so the guest reads config from a regular file via 9p.
    """
    mount_specs: list[tuple[str, Path, str]] = []
    mount_list: list[tuple[str, str]] = []
    for i, rule in enumerate(all_rules.file_rules):
        if not isinstance(rule, BindRule):
            continue
        host_path = Path(rule.source).resolve()
        if host_path.is_file():
            host_path = host_path.parent
        if not host_path.exists():
            continue
        tag = f"pysb_{i}"
        guest_path = rule.dest if rule.dest is not None else f"/app/bind_{i}"
        mount_specs.append((tag, host_path, guest_path))
        mount_list.append((tag, guest_path))
    # Run dir (temp) for exitcode etc.
    if temp.is_dir():
        tag_run = "pysb_run"
        mount_specs.append((tag_run, temp, GUEST_RUN_MOUNT))
        mount_list.append((tag_run, GUEST_RUN_MOUNT))
    # Config dir: dedicated 9p mount so guest sees config.pkl as a regular file (avoids FIFO/9p issues)
    if config_dir is not None and config_dir.is_dir():
        tag_config = "pysb_config"
        mount_specs.append((tag_config, config_dir, GUEST_CONFIG_MOUNT))
        mount_list.append((tag_config, GUEST_CONFIG_MOUNT))
    # Execution dirs: sys.executable, getsitepackages(), sys.path (follow symlinks)
    existing_guest_paths = {guest_path for (_, guest_path) in mount_list}
    for tag, host_path, guest_path in _execution_dirs_mounts():
        if guest_path in existing_guest_paths:
            continue
        existing_guest_paths.add(guest_path)
        mount_specs.append((tag, host_path, guest_path))
        mount_list.append((tag, guest_path))

    # Keep deterministic mount order while preserving semantics:
    # - File rules first (pysb_<idx>) so project paths can override import resolution.
    # - Within file rules, parent paths first, so writable child mounts (e.g. .../tmp)
    #   can override read-only parent mounts.
    # - Runtime/config mounts next, execution dirs last.
    def _mount_order(tag: str, guest_path: str) -> tuple[int, int, int, str]:
        if tag.startswith("pysb_") and tag[5:].isdigit():
            depth = len(Path(guest_path).parts)
            return (0, depth, int(tag[5:]), guest_path)
        if tag == "pysb_config":
            return (1, 0, 0, guest_path)
        if tag == "pysb_run":
            return (1, 1, 0, guest_path)
        if tag.startswith("pysb_exec_") and tag[9:].isdigit():
            return (2, 0, int(tag[9:]), guest_path)
        return (3, 0, 0, guest_path)

    mount_list.sort(key=lambda m: _mount_order(m[0], m[1]))
    mount_specs.sort(key=lambda m: _mount_order(m[0], m[2]))
    return mount_specs, mount_list


def _qemu_binary() -> str:
    """Return the QEMU system binary for the current architecture."""
    arch = platform.machine()
    name = f"qemu-system-{arch}"
    path = which_command(name)
    if path is not None:
        return str(path)
    if arch != "x86_64":
        path = which_command("qemu-system-x86_64")
        if path is not None:
            return str(path)
    return name  # Let subprocess fail with a clear error if not in PATH


class QemuSSEDaemon(VMSSEDaemon):
    """SSE daemon that runs the sandbox inside a QEMU VM.

    Config is embedded in the NoCloud ISO; pysandboxes source is shared via
    virtio-9p so no file copies or HTTP server are needed.
    """

    __slots__ = ("_iso_config",)

    def __init__(
        self, token: str, *, python_args: list[str] | None = None, **kwargs: Any
    ) -> None:
        # Force IPv4 so hostfwd (TCP only on 0.0.0.0) is used; "localhost" can resolve to ::1.
        super().__init__(
            token,
            python_args=python_args or [],
            host="127.0.0.1",
            **kwargs,
        )
        self._iso_config: DaemonParameters | None = None

    @override
    def parse_rules(
        self,
        rules: ConfigLines,
        errors: list[ErrorMsg],
    ) -> tuple[ImmutableDict[str, Any], ConfigLines]:
        """Parse qemu.* lines into os_sandbox_params; pass rest through."""
        params: dict[str, str] = {}
        rest: ConfigLines = []
        for rule in rules:
            if rule.rule.startswith("qemu."):
                part = rule.rule[len("qemu.") :].strip()
                if "=" in part:
                    key, _, val = part.partition("=")
                    params[key.strip()] = val.strip()
                else:
                    params[part.strip()] = ""
            else:
                rest.append(rule)
        return ImmutableDict(params), rest

    def _build_qemu_cmd(
        self,
        all_rules: AllRules,
        temp: Path,
        process_config: "DaemonParameters",
        port: int,
        pipe_path: Path,
        config_dir: Path | None = None,
    ) -> tuple[Args, Environ]:
        """Build QEMU command: one virtio-9p tag per file_rule BindRule + run dir + optional config dir, ISO with 9p_mounts + pipe_name."""
        image_path = get_default_image_path()
        ensure_image(image_path)
        mount_specs, mount_list = _file_rules_mounts(
            all_rules, temp, pipe_path, config_dir=config_dir
        )
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}"
        config_guest_path = f"{GUEST_CONFIG_MOUNT}/config.pkl" if config_dir else None
        nocloud_iso = prepare_guest_env(
            temp,
            process_config,
            pipe_path=pipe_path,
            mounts=mount_list,
            pipe_run_guest_path=GUEST_RUN_MOUNT,
            python_version=python_version,
            python_exe=sys.executable,
            config_guest_path=config_guest_path,
        )

        use_kvm = all_rules.os_sandbox_params.get("qemu.use_kvm", "true").lower() in (
            "true",
            "1",
            "yes",
        )
        enable_kvm = ["-enable-kvm"] if use_kvm and is_kvm_available() else []

        # Default 2 GiB: Ubuntu cloud images + Python need ~2G to avoid OOM (see Ubuntu QEMU docs)
        raw_memory = all_rules.os_sandbox_params.get("qemu.memory", "2048").strip()
        if raw_memory and (
            raw_memory.isdigit()
            or (
                len(raw_memory) > 1
                and raw_memory[:-1].isdigit()
                and raw_memory[-1] in "gGmM"
            )
        ):
            memory = raw_memory
        else:
            memory = "2048"

        net = [
            "-nic",
            f"user,hostfwd=tcp::{port}-:{port},model=virtio-net-pci",
        ]

        virtfs_args: Args = []
        for tag, host_path, guest_path in mount_specs:
            # Use mapped-xattr for all mounts so guest sees regular files correctly (e.g. config file).
            security = "mapped-xattr"
            virtfs_args.extend(
                [
                    "-virtfs",
                    f"local,path={host_path!s},id={tag},security_model={security},mount_tag={tag}",
                ]
            )
            logger.debug("qemu 9p: %s -> %s", tag, guest_path)

        qga = [
            "-device",
            "virtio-serial-pci",
            "-device",
            "virtserialport,name=org.qemu.guest_agent.0",
        ]

        # Ubuntu cloud images use .img extension but are QCOW2 format (see Ubuntu docs)
        use_qcow2 = image_path.suffix == ".qcow2" or (
            image_path.suffix == ".img" and "cloudimg" in image_path.name
        )
        drive_image = (
            f"file={image_path!s},format=qcow2,if=virtio"
            if use_qcow2
            else f"file={image_path!s},format=raw,if=virtio"
        )
        drive_nocloud = f"file={nocloud_iso!s},format=raw,if=virtio"
        cmd: Args = [
            _qemu_binary(),
            *enable_kvm,
            "-m",
            memory,
            "-snapshot",
            "-drive",
            drive_image,
            "-drive",
            drive_nocloud,
            "-nographic",
            *net,
            *virtfs_args,
            *qga,
        ]
        return cmd, {}

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: dict[str, str],
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Build QEMU command for python_sb path (config pre-set via _iso_config).

        For the daemon path (_re_start_cmd), this returns an empty command since
        _re_start_cmd builds everything itself. For the python_sb path, process_config
        is set as _iso_config before this call so the ISO can be built with it embedded.
        """
        process_config = getattr(self, "_iso_config", None)
        if process_config is None:
            # Daemon path: _re_start_cmd handles ISO creation and launch
            return [], {}
        # python_sb path: config in dedicated 9p dir (same as _re_start_cmd)
        config_dir = temp / "pysb_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.pkl").write_bytes(pickle.dumps(process_config))
        return self._build_qemu_cmd(
            all_rules,
            temp,
            process_config,
            self.port,
            pipe_path,
            config_dir=config_dir,
        )

    @override
    async def _re_start_cmd(
        self,
        all_rules: AllRules,
        args: Args,
        extra_envs: dict[str, str],
        pipe_path: Path,
        port: int,
        *,
        log_level: int,
        init_fn: Any,
    ) -> None:
        """Build NoCloud ISO (bootstrap + pipe_name), then launch QEMU.

        Guest mounts /app (file_rules root) and /mnt/pysandbox_run (temp with FIFO)
        via 9p, runs main_sandbox --_named-pipe; host writes config to the pipe
        when the guest opens it (same flow as bwrap/unshare).
        """
        from .client_subprocess_sse_daemon import get_callable_info

        self._is_started = False
        self._accept_incoming = False
        init_fn_ref = ""
        if init_fn:
            module, func_ref = get_callable_info(init_fn)
            init_fn_ref = f"{module}:{func_ref}"

        dns_guest = [IPv4Address("10.0.2.3")]
        netfilter_rules = rule_to_netfilter(
            all_rules.socket_rules, dns_guest, is_ipv6=False
        )
        # Allow host (10.0.2.2 in QEMU user mode) to reach the SSE server port.
        if "COMMIT" in netfilter_rules:
            idx = netfilter_rules.index("COMMIT")
            sse_allow = (
                f"-A INPUT -p tcp -s 10.0.2.2/32 --dport {port} "
                "-m conntrack --ctstate NEW,ESTABLISHED -j ACCEPT"
            )
            netfilter_rules = (
                list(netfilter_rules[:idx]) + [sse_allow] + list(netfilter_rules[idx:])
            )
        netfilter_rules = tuple(netfilter_rules)

        process_config = DaemonParameters(
            all_rules=all_rules,
            log_level=log_level,
            log_format=get_log_formatter(),
            use_rich_handler=use_rich_handler(),
            token=self._token,
            port=port,
            init_fn=init_fn_ref,
            netfilter_rules=tuple(netfilter_rules),
            guest_run_dir=GUEST_RUN_MOUNT,
        )

        env: dict[str, str]
        if all_rules.learn:
            env = {**dict(os.environ), **dict(all_rules.envs)}
        else:
            env = dict(all_rules.envs)
        env = {**env, **extra_envs}

        temp = pipe_path.parent
        # Config in a dedicated 9p-mounted dir so the guest sees a regular file (avoids FIFO/9p blocking issues)
        config_dir = temp / "pysb_config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.pkl").write_bytes(pickle.dumps(process_config))

        cmd, _ = self._build_qemu_cmd(
            all_rules, temp, process_config, port, pipe_path, config_dir=config_dir
        )

        logger.debug(
            "Launch QEMU: %s", " ".join((repr(a) if " " in a else a for a in cmd))
        )

        # Config is in config_dir (9p); no FIFO needed
        def _noop_config_writer(_: DaemonParameters) -> None:
            pass

        show_boot = all_rules.os_sandbox_params.get(
            "qemu.show_boot_console", "false"
        ).lower() in ("true", "1", "yes")
        # When show_boot_console is false (default), redirect QEMU stdout/stderr so
        # boot/kernel/cloud-init traces are hidden; Python output is streamed via SSE.
        launch_kwargs: dict[str, Any] = dict(
            cmd=cmd,
            pipe_path=pipe_path,
            envs=Envs(env),
            process_config=process_config,
            config_writer=_noop_config_writer,
        )
        if not show_boot:
            launch_kwargs["stdout"] = subprocess.DEVNULL
            launch_kwargs["stderr"] = subprocess.DEVNULL
        self._process = await launch_sandbox(**launch_kwargs)

        await self._on_process_started()

        gc.collect()
        ping_url = self.base_url.replace("{PORT}", str(port)) + "/ping"
        logger.info(
            "Waiting %.0fs for QEMU guest to boot, then pinging %s (max %d attempts)",
            QEMU_BOOT_DELAY,
            ping_url,
            QEMU_LOOP_FOR_PING,
        )
        await asyncio.sleep(QEMU_BOOT_DELAY)
        import socket

        import aiohttp
        from aiohttp import ClientConnectorError, ClientTimeout, ServerDisconnectedError

        # Force IPv4 so QEMU hostfwd is used (hostfwd is TCP on 0.0.0.0, not IPv6).
        connector = aiohttp.TCPConnector(family=socket.AF_INET)
        async with aiohttp.ClientSession(connector=connector) as session:
            count_loop = 0
            while True:
                try:
                    count_loop += 1
                    if count_loop > QEMU_LOOP_FOR_PING:
                        logger.error(
                            "Cannot connect to sandbox daemon after %d attempts (%s)",
                            count_loop - 1,
                            ping_url,
                        )
                        raise SystemExit(-1)
                    async with session.get(
                        ping_url,
                        timeout=ClientTimeout(total=TIMEOUT_FOR_PING),
                    ) as response:
                        if response.status == 200:
                            logger.debug(
                                "Ping succeeded on attempt %d to %s",
                                count_loop,
                                ping_url,
                            )
                            break
                        logger.warning(
                            "Ping attempt %d: unexpected status %s from %s",
                            count_loop,
                            response.status,
                            ping_url,
                        )
                        raise RuntimeError(
                            f"Unexpected status {response.status} from {ping_url}"
                        )
                except (
                    TimeoutError,
                    ClientConnectorError,
                    ServerDisconnectedError,
                ) as e:
                    if count_loop % 25 == 0 or count_loop <= 3:
                        logger.debug(
                            "Ping attempt %d/%d failed: %s",
                            count_loop,
                            QEMU_LOOP_FOR_PING,
                            type(e).__name__,
                        )
                await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)

        await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)
        logger.info(
            "QEMU sandbox daemon is up and running at %s (host will now accept RPCs)",
            ping_url,
        )
        self._is_started = True
        self._accept_incoming = True
