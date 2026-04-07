# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""QEMU-based VM SSE daemon for PySandboxes.

Runs the sandbox inside a QEMU VM. Uses -net user + hostfwd for SSE,
virtio-9p to expose the config pipe to the guest, and optional QGA for shutdown.
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
from .qemu_image import ensure_image, get_default_image_path, is_kvm_available
from .sse_client_subprocess_daemon import (
    DaemonParameters,
    get_log_formatter,
    launch_sandbox,
    use_rich_handler,
)
from .tools import which_command
from .vm_sse_daemon import VMSSEDaemon

logger = logging.getLogger(__name__)

# Fixed port inside the guest where the SSE server listens
GUEST_SSE_PORT = 8765

# 9p mount tag and guest path (guest mounts with: mount -t 9p -o trans=virtio TAG GUEST_PATH)
QEMU_9P_MOUNT_TAG = "pysandbox_config"


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
    """SSE daemon that runs the sandbox inside a QEMU VM."""

    __slots__ = ()

    def __init__(
        self, token: str, *, python_args: list[str] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(token, python_args=python_args or [], **kwargs)

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

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: dict[str, str],
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Build the QEMU command line (no Python args)."""
        custom_image = all_rules.os_sandbox_params.get("qemu.image")
        if custom_image:
            image_path = Path(custom_image).expanduser().resolve()
            if not image_path.is_file():
                raise FileNotFoundError(f"qemu.image path is not a file: {image_path}")
        else:
            image_path = get_default_image_path()
            ensure_image(image_path)

        use_kvm = all_rules.os_sandbox_params.get("qemu.use_kvm", "true").lower() in (
            "true",
            "1",
            "yes",
        )
        if use_kvm and is_kvm_available():
            enable_kvm = ["-enable-kvm"]
        else:
            enable_kvm = []

        raw_memory = all_rules.os_sandbox_params.get("qemu.memory", "256")
        memory = raw_memory if raw_memory.isdigit() else "256"
        host_port = self.port

        # -virtfs: expose temp dir to guest so it can read the config pipe
        virtfs = [
            "-virtfs",
            f"local,path={temp.resolve()!s},mount_tag={QEMU_9P_MOUNT_TAG},security_model=mapped",
        ]

        # -net user,hostfwd: forward host port to guest GUEST_SSE_PORT
        net = [
            "-net",
            f"user,hostfwd=tcp::{host_port}-:{GUEST_SSE_PORT}",
        ]

        # -device virtio-serial for QGA (guest can use qemu-guest-agent)
        qga = [
            "-device",
            "virtio-serial-pci",
            "-device",
            "virtserialport,name=org.qemu.guest_agent.0",
        ]

        cmd: Args = [
            _qemu_binary(),
            *enable_kvm,
            "-m",
            memory,
            "-drive",
            (
                f"file={image_path!s},format=qcow2,if=virtio"
                if image_path.suffix == ".qcow2"
                else f"file={image_path!s},format=raw,if=virtio"
            ),
            "-nographic",
            *virtfs,
            *net,
            *qga,
        ]
        return cmd, {}

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
        """Launch QEMU with config pipe; do not append --_named-pipe to args."""
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

        logger.debug(
            "Launch QEMU: %s", " ".join((repr(a) if " " in a else a for a in args))
        )
        self._process = await launch_sandbox(
            args,
            pipe_path=pipe_path,
            envs=Envs(env),
            process_config=process_config,
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
