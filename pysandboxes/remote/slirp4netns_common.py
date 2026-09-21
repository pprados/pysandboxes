# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Shared slirp4netns helpers for bwrap and unshare daemons.

Both providers use slirp4netns for user-land networking when the sandbox runs
in a network namespace. This module centralizes constants, port extraction,
port forwarding via the slirp4netns API, and the slirp watcher thread logic.
"""

import json
import logging
import os
import socket as socket_mod
import stat
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from ..all_rules import AllRules
from ..guard_socket import Action, Direction, Kind
from .tools import set_pdeathsig

logger = logging.getLogger(__name__)

# slirp4netns guest addressing (same for bwrap and unshare)
SLIRP_GW = "10.0.2.2"
SLIRP_DNS = "10.0.2.3"
SLIRP_GUEST_ADDR = "10.0.2.100"
SLIRP_INTERFACE = "tap0"
SLIRP_WATCHER_TIMEOUT = 30


def is_socket(path: str) -> bool:
    """Return True if path is a Unix socket."""
    try:
        return stat.S_ISSOCK(os.stat(path).st_mode)
    except (OSError, ValueError):
        return False


def extract_port_forwards(
    all_rules: AllRules,
    sse_port: int,
    *,
    log_wildcard: bool = True,
) -> str:
    """Build port forwarding spec for slirp4netns (e.g. 'tcp:PORT tcp:80').

    Collects TCP/UDP ports from socket rules (ALLOW + IN) and always includes
    sse_port. Used by both bwrap and unshare to configure add_hostfwd.
    """
    tcp_ports: set[int] = {sse_port}
    udp_ports: set[int] = set()
    for rule in all_rules.socket_rules:
        if rule.action != Action.ALLOW or Direction.IN not in rule.directions:
            continue
        ports = rule.mask.ports
        if isinstance(ports, range) and len(ports) > 1000:
            if log_wildcard:
                logger.warning(
                    "Cannot forward wildcard port range from rule '%s'. " "Use explicit ports instead.",
                    rule.config.rule,
                )
            continue
        port_list = list(ports)
        for kind in rule.mask.kinds:
            if kind == Kind.TCP:
                tcp_ports.update(port_list)
            elif kind == Kind.UDP:
                udp_ports.update(port_list)
    parts = [f"tcp:{p}" for p in sorted(tcp_ports)]
    parts += [f"udp:{p}" for p in sorted(udp_ports)]
    return " ".join(parts)


def setup_port_forwarding(
    api_socket: str,
    ports_spec: str,
    *,
    socket_wait_attempts: int = 50,
    socket_wait_interval: float = 0.1,
) -> None:
    """Forward host ports to sandbox via slirp4netns API socket.

    Sends add_hostfwd for each proto:port in ports_spec (e.g. 'tcp:8080 udp:53').
    Host is 127.0.0.1, guest is SLIRP_GUEST_ADDR.
    """
    if not ports_spec:
        return
    for _ in range(socket_wait_attempts):
        if os.path.exists(api_socket) and is_socket(api_socket):
            break
        time.sleep(socket_wait_interval)
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
                        "guest_addr": SLIRP_GUEST_ADDR,
                        "guest_port": port,
                    },
                }
            )
            s.sendall(cmd.encode() + b"\0")
            s.recv(4096)
            s.close()
        except Exception:
            pass


def _wait_for_pid_file(
    pid_file: str,
    timeout: int,
    shutdown_event: threading.Event,
) -> int | None:
    """Poll pid_file until it contains a PID or timeout/shutdown. Return PID or None."""
    deadline = time.monotonic() + timeout
    while True:
        if shutdown_event.is_set():
            return None
        if time.monotonic() > deadline:
            logger.error(
                "slirp_watcher: timed out waiting for pid_file %s after %ds",
                pid_file,
                timeout,
            )
            return None
        try:
            content = Path(pid_file).read_text().strip()
            if content:
                return int(content)
        except (FileNotFoundError, ValueError):
            pass
        time.sleep(0.05)


def run_slirp_watcher(
    shutdown_event: threading.Event,
    pipe_w: int,
    api_socket: str,
    *,
    child_pid: int | None = None,
    pid_file: str | None = None,
    process_holder: list[subprocess.Popen[bytes] | None] | None = None,
    timeout: int = SLIRP_WATCHER_TIMEOUT,
) -> None:
    """Background thread: run slirp4netns for the sandbox network namespace.

    Either child_pid (bwrap: known at launch) or pid_file (unshare: written
    after unshare starts) must be provided. Signals readiness by writing to
    pipe_w. Puts the Popen instance in process_holder[0] when started so the
    daemon can kill it on shutdown.
    """
    try:
        _run_slirp_watcher(
            shutdown_event,
            pipe_w,
            api_socket,
            child_pid=child_pid,
            pid_file=pid_file,
            process_holder=process_holder,
            timeout=timeout,
        )
    finally:
        remove_slirp_temp_files(pid_file, api_socket)


def _run_slirp_watcher(
    shutdown_event: threading.Event,
    pipe_w: int,
    api_socket: str,
    *,
    child_pid: int | None = None,
    pid_file: str | None = None,
    process_holder: list[subprocess.Popen[bytes] | None] | None = None,
    timeout: int = SLIRP_WATCHER_TIMEOUT,
) -> None:
    """Body of :func:`run_slirp_watcher`, which owns the temporary files it leaves."""
    if child_pid is not None:
        pid = child_pid
    elif pid_file is not None:
        pid_maybe = _wait_for_pid_file(pid_file, timeout, shutdown_event)
        if pid_maybe is None:
            try:
                os.close(pipe_w)
            except OSError:
                pass
            return
        pid = pid_maybe
        logger.debug("slirp_watcher: got pid=%s", pid)
    else:
        logger.error("slirp_watcher: need child_pid or pid_file")
        try:
            os.close(pipe_w)
        except OSError:
            pass
        return

    if shutdown_event.is_set():
        try:
            os.close(pipe_w)
        except OSError:
            pass
        return

    proc: subprocess.Popen[bytes] | None = None
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
            str(pid),
            SLIRP_INTERFACE,
        ]
        logger.debug("slirp_watcher: launching: %s", " ".join(slirp_arg))
        # slirp4netns holds the sandbox network namespace open itself, so it does not
        # notice its target dying and outlives the whole of pysandboxes -- keeping a
        # listening socket on the host for every forwarded port. PR_SET_PDEATHSIG makes
        # the kernel signal it when the thread that spawned it goes away, which covers
        # the paths no `finally` reaches: SIGKILL, a crash, interpreter teardown.
        proc = subprocess.Popen(
            slirp_arg,
            stdout=subprocess.DEVNULL,
            stderr=(subprocess.PIPE if logger.isEnabledFor(logging.DEBUG) else subprocess.DEVNULL),
            pass_fds=(pipe_w,),
            preexec_fn=set_pdeathsig,  # noqa: PLW1509
        )
        if process_holder is not None:
            process_holder.clear()
            process_holder.append(proc)
        logger.debug("slirp_watcher: slirp4netns launched (pid=%d)", proc.pid)
        while True:
            try:
                proc.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                if shutdown_event.is_set():
                    return
        stderr_output = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        if shutdown_event.is_set():
            return
        logger.debug("slirp_watcher: slirp4netns exited with code %s", proc.returncode)
        if stderr_output:
            logger.error("slirp_watcher: slirp4netns stderr: %s", stderr_output.strip())
        if proc.returncode not in (0, -9):
            logger.warning("slirp_watcher: slirp4netns exited with code %s", proc.returncode)
    except Exception:
        logger.exception("slirp_watcher: exception launching slirp4netns")
    finally:
        if process_holder is not None:
            process_holder.clear()
            process_holder.append(None)
        try:
            os.close(pipe_w)
        except OSError:
            pass


def make_slirp_temp_files() -> tuple[str, str]:
    """Create temporary pid file and API socket path for slirp4netns.

    Returns (pid_file_path, api_socket_path). The API socket path is unlinked
    so slirp4netns can create it as a socket. Both are the caller's to remove
    afterwards, through :func:`remove_slirp_temp_files`.
    """
    fd, pid_file = tempfile.mkstemp()
    os.close(fd)
    fd, api_socket = tempfile.mkstemp()
    os.close(fd)
    os.unlink(api_socket)
    return pid_file, api_socket


def remove_slirp_temp_files(pid_file: str | None, api_socket: str | None) -> None:
    """Remove what a slirp4netns run leaves in the temporary directory.

    slirp4netns re-creates ``api_socket`` as a Unix socket, and the sandbox writes
    its pid into ``pid_file``; neither goes away on its own. Call this from the
    shutdown path as well as from the watcher thread: the thread is a daemon one,
    so the interpreter can exit while it still waits on slirp4netns, and its
    ``finally`` then never runs.
    """
    for path in (pid_file, api_socket):
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
