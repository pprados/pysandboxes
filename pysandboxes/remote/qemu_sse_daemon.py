# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""QEMU-based VM SSE daemon for PySandboxes.

Runs the sandbox inside a QEMU VM. Uses -net user + hostfwd for SSE,
virtio-9p to expose pysandboxes source and venv to the guest.
Config is embedded in the NoCloud ISO (no separate HTTP server needed).
"""

import asyncio
import gc
import logging
import os
import platform
import sys
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any

try:
    from typing import override
except ImportError:
    from typing_extensions import override

from ..all_rules import AllRules
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg
from ..netfilter import rule_to_netfilter
from ..sb_types import Args, ConfigLines, Envs
from ..tools import Environ
from .parameters import (
    INTERVAL_FOR_PING_DAEMON,
    LOOP_FOR_PING,
    TIMEOUT_FOR_PING,
)
from .qemu_guest_bootstrap import PYSANDBOXES_9P_TAG, VENV_9P_TAG, prepare_guest_env
from .qemu_image import ensure_image, get_default_image_path, is_kvm_available
from .sse_client_subprocess_daemon import (
    DaemonParameters,
    find_free_port,
    get_log_formatter,
    launch_sandbox,
    use_rich_handler,
)
from .tools import which_command
from .vm_sse_daemon import VMSSEDaemon

logger = logging.getLogger(__name__)


def _host_venv_site_packages() -> Path | None:
    """Return host venv site-packages path if running in a venv, else None.

    When not None, the guest can mount it via 9p and use it as PYTHONPATH
    instead of reinstalling deps with pip.
    """
    prefix = Path(sys.prefix).resolve()
    base = Path(sys.base_prefix).resolve()
    if prefix == base:
        return None
    # e.g. prefix/lib/python3.12/site-packages
    py_ver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    site = prefix / "lib" / py_ver / "site-packages"
    if not site.is_dir():
        return None
    return site


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
        super().__init__(token, python_args=python_args or [], **kwargs)
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

    @override
    def update_rules_and_activate(
        self,
        *,
        envs: Envs,
        all_rules: AllRules,
        temp: Path,
    ) -> AllRules:
        return all_rules

    def _build_qemu_cmd(
        self,
        all_rules: AllRules,
        temp: Path,
        process_config: "DaemonParameters",
        port: int,
    ) -> tuple[Args, Environ]:
        """Build QEMU command after creating the NoCloud ISO with embedded config."""
        image_path = get_default_image_path()
        ensure_image(image_path)
        venv_site = _host_venv_site_packages()

        from .. import __path__ as _pkg_paths

        pkg_parent = Path(_pkg_paths[0]).resolve().parent

        nocloud_iso = prepare_guest_env(
            temp,
            process_config,
            venv_site_packages_path=venv_site,
            use_pysandboxes_9p=True,
        )

        use_kvm = all_rules.os_sandbox_params.get("qemu.use_kvm", "true").lower() in (
            "true",
            "1",
            "yes",
        )
        enable_kvm = ["-enable-kvm"] if use_kvm and is_kvm_available() else []

        raw_memory = all_rules.os_sandbox_params.get("qemu.memory", "256")
        memory = raw_memory if raw_memory.isdigit() else "256"

        # Same port on host and guest: host finds a free port, guest listens on it
        net = [
            "-nic",
            f"user,hostfwd=tcp::{port}-:{port},model=virtio-net-pci",
        ]

        virtfs_pysandboxes: Args = []
        pkg_parent_str = str(pkg_parent)
        if pkg_parent.is_dir():
            virtfs_pysandboxes = [
                "-virtfs",
                f"local,path={pkg_parent_str},id={PYSANDBOXES_9P_TAG},security_model=mapped-xattr,mount_tag={PYSANDBOXES_9P_TAG}",
            ]
        else:
            logger.warning(
                "qemu 9p: pysandboxes parent dir not found: %s", pkg_parent_str
            )

        virtfs_venv: Args = []
        if venv_site is not None:
            path_str = str(venv_site)
            if venv_site.is_dir():
                try:
                    entries = list(venv_site.iterdir())[:5]
                    logger.info(
                        "qemu 9p: sharing %s (mount_tag=%s) sample entries: %s",
                        path_str,
                        VENV_9P_TAG,
                        [e.name for e in entries],
                    )
                except OSError as e:
                    logger.warning(
                        "qemu 9p: cannot list site-packages %s: %s", path_str, e
                    )
                virtfs_venv = [
                    "-virtfs",
                    f"local,path={path_str},id={VENV_9P_TAG},security_model=mapped,mount_tag={VENV_9P_TAG}",
                ]
            else:
                logger.warning(
                    "qemu 9p: venv site-packages path does not exist: %s", path_str
                )

        qga = [
            "-device",
            "virtio-serial-pci",
            "-device",
            "virtserialport,name=org.qemu.guest_agent.0",
        ]

        drive_image = (
            f"file={image_path!s},format=qcow2,if=virtio"
            if image_path.suffix == ".qcow2"
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
            *virtfs_pysandboxes,
            *virtfs_venv,
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
        # python_sb path: build ISO with embedded config, return full QEMU command
        return self._build_qemu_cmd(all_rules, temp, process_config, self.port)

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
        """Build NoCloud ISO with embedded config, then launch QEMU.

        The ISO is created in the shared tmpdir (pipe_path.parent) and includes
        config.pkl so the guest needs no HTTP server to receive its configuration.
        Pysandboxes source is exposed to the guest via virtio-9p.
        """
        from .sse_client_subprocess_daemon import get_callable_info

        self._is_started = False
        self._accept_incoming = False
        init_fn_ref = ""
        if init_fn:
            module, func_ref = get_callable_info(init_fn)
            init_fn_ref = f"{module}:{func_ref}"

        # Build netfilter rules for the guest (QEMU user net often uses 10.0.2.3 as DNS)
        dns_guest = [IPv4Address("10.0.2.3")]
        netfilter_rules = rule_to_netfilter(
            all_rules.socket_rules, dns_guest, is_ipv6=False
        )

        process_config = DaemonParameters(
            all_rules=all_rules,
            log_level=log_level,
            log_format=get_log_formatter(),
            use_rich_handler=use_rich_handler(),
            token=self._token,
            port=port,
            init_fn=init_fn_ref,
            netfilter_rules=tuple(netfilter_rules),
        )

        env: dict[str, str]
        if all_rules.learn:
            env = {**dict(os.environ), **dict(all_rules.envs)}
        else:
            env = dict(all_rules.envs)
        env = {**env, **extra_envs}

        # pipe_path.parent is the tmpdir created by _re_start (alive until we return)
        cmd, _ = self._build_qemu_cmd(all_rules, pipe_path.parent, process_config, port)

        logger.debug(
            "Launch QEMU: %s", " ".join((repr(a) if " " in a else a for a in cmd))
        )
        # Config is embedded in the ISO; pass a no-op config_writer to skip FIFO creation.
        # Config is embedded in the ISO; pass a no-op config_writer to skip FIFO creation.
        self._process = await launch_sandbox(
            cmd,
            pipe_path=pipe_path,
            envs=Envs(env),
            process_config=process_config,
            config_writer=lambda _: None,
        )

        await self._on_process_started()

        gc.collect()
        ping_url = self.base_url.replace("{PORT}", str(port)) + "/ping"
        logger.debug("Try to call %s", ping_url)
        import aiohttp
        from aiohttp import ClientConnectorError, ClientTimeout, ServerDisconnectedError

        async with aiohttp.ClientSession() as session:
            count_loop = 0
            while True:
                try:
                    count_loop += 1
                    if count_loop > LOOP_FOR_PING:
                        logger.error("Cannot connect to sandbox daemon (%s)", ping_url)
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
                except (TimeoutError, ClientConnectorError, ServerDisconnectedError):
                    pass
                await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)

        await asyncio.sleep(INTERVAL_FOR_PING_DAEMON)
        logger.debug("Sandbox daemon is up and running")
        self._is_started = True
        self._accept_incoming = True
