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
import pickle
import platform
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any, Callable

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
from .qemu_guest_bootstrap import VENV_9P_TAG, prepare_guest_env
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

# Fixed port inside the guest where the SSE server listens
GUEST_SSE_PORT = 8765  # FIXME


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


# Field names that must be Path; serialized as str for cross-version pickle.
_PATH_FIELDS = frozenset(("root_path", "learning_path"))


def _config_paths_to_str(obj: Any) -> Any:
    """Recursively replace Path with str so pickle stream has no pathlib (no pathlib._local)."""
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "_asdict") and hasattr(obj, "_fields"):
        return type(obj)(
            **{k: _config_paths_to_str(v) for k, v in obj._asdict().items()}
        )
    if isinstance(obj, dict):
        return {k: _config_paths_to_str(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(_config_paths_to_str(x) for x in obj)
    return obj


def _start_config_server(port: int, process_config: DaemonParameters) -> None:  # FIXME
    """Start a one-request HTTP server in a daemon thread to serve config to the guest."""
    # Serialize with Path replaced by str so guest never needs pathlib._local.
    safe_config = _config_paths_to_str(process_config)
    payload = pickle.dumps(safe_config, protocol=pickle.HIGHEST_PROTOCOL)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/config.pkl":
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            logger.debug("config server %s", format % args)

    def run() -> None:
        with HTTPServer(("0.0.0.0", port), Handler) as httpd:
            httpd.serve_forever()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    logger.debug("Config HTTP server listening on 0.0.0.0:%s for guest", port)


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
    """SSE daemon that runs the sandbox inside a QEMU VM. Config via HTTP (no 9p)."""

    __slots__ = ("_config_port",)

    def __init__(
        self, token: str, *, python_args: list[str] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(token, python_args=python_args or [], **kwargs)
        self._config_port = 0  # set in subprocess_cmd before first launch

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
        """Build the QEMU command line (no Python args). Config via HTTP.

        If the host runs in a venv, its site-packages are shared via 9p so the
        guest does not need to pip install.
        """
        image_path = get_default_image_path()
        ensure_image(image_path)  # downloads with progress if missing
        self._config_port = find_free_port()
        venv_site = _host_venv_site_packages()
        nocloud_iso = prepare_guest_env(
            temp, self._config_port, venv_site_packages_path=venv_site
        )

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

        # -nic user + virtio-net: QEMU provides DHCP; guest fetches config from 10.0.2.2:config_port
        net = [
            "-nic",
            f"user,hostfwd=tcp::{host_port}-:{GUEST_SSE_PORT},model=virtio-net-pci",
        ]

        # -virtfs: share host venv site-packages so guest reuses them (no pip install)
        virtfs_venv: Args = []
        if venv_site is not None:
            path_str = str(venv_site)
            if not venv_site.is_dir():
                logger.warning(
                    "qemu 9p: venv site-packages path does not exist or is not a dir: %s",
                    path_str,
                )
            else:
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

        # -device virtio-serial for QGA (guest can use qemu-guest-agent)
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
            "-snapshot",  # do not write to the base image (avoids lock conflict)
            "-drive",
            drive_image,
            "-drive",
            drive_nocloud,
            "-nographic",
            *net,
            *virtfs_venv,
            *qga,
        ]
        return cmd, {}

    def get_config_writer(self) -> "Callable[[DaemonParameters], None]":
        """Return a callable that starts the HTTP config server (used instead of FIFO)."""
        port = self._config_port
        return lambda cfg: _start_config_server(port, cfg)

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
        config_writer = lambda cfg: _start_config_server(self._config_port, cfg)
        self._process = await launch_sandbox(
            args,
            pipe_path=pipe_path,
            envs=Envs(env),
            process_config=process_config,
            config_writer=config_writer,
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
