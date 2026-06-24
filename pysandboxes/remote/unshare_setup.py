# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Namespace setup module — runs inside the unshared namespace.

Replaces unshare_setup.sh. This script is executed by the unshare command
inside user/network/mount namespaces. It:
1. Signals readiness to the launcher (writes PID to PID_FILE)
2. Waits for network (reads from fd 3, provided by slirp4netns)
3. Configures loopback and iptables
4. Builds a chroot with bind-mounted paths
5. Execs into the final sandboxed command with dropped capabilities
"""

from __future__ import annotations

import json
import logging
import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from pysandboxes.config import DEBUG

SLIRP_INTERFACE = "tap0"
# slirp4netns -c uses 10.0.2.0/24; gateway 10.0.2.2, optional tap IP 10.0.2.15 if not set by -c
SLIRP_GATEWAY = "10.0.2.2"
SLIRP_TAP_CIDR = "10.0.2.15/24"

logger = logging.getLogger(__name__)


def _debug_log() -> None:
    sandbox_level = logging.DEBUG
    format = "%(levelname)-5s [%(process)d] %(name)s: %(message)s"
    logging.getLogger("Pysandboxes").setLevel(logging.INFO)
    logging.getLogger("pysandboxes").setLevel(sandbox_level)
    logging.getLogger("pysandboxes.remote.firejail_daemon").setLevel(sandbox_level)
    logging.basicConfig(
        level=sandbox_level,
        format=format,
    )


@dataclass
class UnshareSetupConfig:
    """Configuration passed from the daemon to the setup process via JSON."""

    dns_servers: list[str]
    hosts: list[str]
    mounts_ro: list[tuple[str, str]]  # (source, dest)
    mounts_rw: list[tuple[str, str]]
    named_pipe: str
    netfilter_rules: list[str]
    current_dir: str
    ignore_paths: list[str]  # paths relative to current_dir to mask (overlay with no-access)
    sandbox_envs: dict[str, str]  # the profile's env= whitelist, all the sandbox may see

    def to_json(self) -> str:
        return json.dumps(
            {
                "dns_servers": self.dns_servers,
                "hosts": self.hosts,
                "mounts_ro": self.mounts_ro,
                "mounts_rw": self.mounts_rw,
                "named_pipe": self.named_pipe,
                "netfilter_rules": self.netfilter_rules,
                "current_dir": self.current_dir,
                "ignore_paths": self.ignore_paths,
                "sandbox_envs": self.sandbox_envs,
            }
        )

    @classmethod
    def from_json(cls, data: str) -> UnshareSetupConfig:
        d = json.loads(data)
        return cls(
            dns_servers=d["dns_servers"],
            hosts=d["hosts"],
            mounts_ro=[tuple(m) for m in d["mounts_ro"]],
            mounts_rw=[tuple(m) for m in d["mounts_rw"]],
            named_pipe=d["named_pipe"],
            netfilter_rules=d["netfilter_rules"],
            current_dir=d["current_dir"],
            ignore_paths=d.get("ignore_paths", []),
            sandbox_envs=d.get("sandbox_envs", {}),
        )


def _run(cmd: list[str], check=True, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """Run a command, raising on failure."""
    logger.debug("  %s", " ".join(cmd))
    subprocess.run(cmd, check=check, **kwargs)


def _mount_bind(src: str, dst: str, new_root: str, readonly: bool) -> None:
    """Bind-mount src to new_root/dst, optionally read-only."""
    if not os.path.exists(src):
        logger.debug(f"mount {src=} not exist")
        return
    full_dst = new_root + dst
    # logger.debug(f"mount {full_dst=}")
    if os.path.isdir(src):
        os.makedirs(full_dst, exist_ok=True)
    else:
        os.makedirs(os.path.dirname(full_dst), exist_ok=True)
        if not os.path.exists(full_dst):
            Path(full_dst).touch()
    _run(["mount", "--rbind", src, full_dst])
    if readonly:
        _run(["mount", "-o", "remount,ro,bind,nosuid,nodev", full_dst])
    # logger.debug(f"")


def _is_reachable_in_chroot(path: str, new_root: str, max_hops: int = 32) -> bool:
    """True when path still resolves once new_root has become the filesystem root.

    Symlink targets are followed the way the kernel will inside the chroot: an
    absolute target is resolved against new_root, not against the host root. A
    link aiming at a host path that was never mounted therefore dangles, and
    binding a placeholder over it would land outside the sandbox.
    """
    root = os.path.normpath(new_root)
    current = path
    for _ in range(max_hops):
        if not os.path.islink(current):
            return os.path.exists(current)
        target = os.readlink(current)
        if os.path.isabs(target):
            current = os.path.normpath(os.path.join(root, target.lstrip("/")))
        else:
            current = os.path.normpath(os.path.join(os.path.dirname(current), target))
        if not current.startswith(root + os.sep):
            return False
    return False


def _ensure_mount_target(target: str, new_root: str) -> None:
    """Ensure a mount target exists, resolving symlinks within the chroot."""
    if os.path.islink(target):
        link_target = os.readlink(target)
        if link_target.startswith("/"):
            resolved = new_root + link_target
        else:
            resolved = os.path.normpath(os.path.join(os.path.dirname(target), link_target))
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        Path(resolved).touch()
    elif not os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        Path(target).touch()


def main() -> None:
    """Entry point for unshare_setup, called as `python -m pysandboxes.remote.unshare_setup`."""
    # Usage: python -m ... <config_path> -- <command> [args...]
    logger.debug("************* unshare_setup *************")
    args = sys.argv[1:]
    if not args:
        print("Usage: unshare_setup <config_path> -- <command> [args...]", file=sys.stderr)
        sys.exit(1)

    config_path = args[0]
    # Find separator
    if "--" in args:
        sep_idx = args.index("--")
        command = args[sep_idx + 1 :]
    else:
        command = args[1:]

    # Read configuration
    logger.debug("load config ...")
    txt_config = Path(config_path).read_text()
    config = UnshareSetupConfig.from_json(txt_config)
    logger.debug(f"\n{json.dumps(json.loads(txt_config),indent=2)}")

    # --- A. Wait for network ---
    # Note: PID_FILE is written by the daemon (sse_unshare_daemon.py) with the
    # host-visible PID needed by slirp4netns. Do NOT overwrite it here with
    # os.getpid() which returns the namespace PID (useless for slirp4netns).

    # Wait for slirp4netns readiness on the fd passed via SLIRP_READY_FD env var
    ready_fd = int(os.environ.get("SLIRP_READY_FD", "3"))
    slirp_timeout = 30  # seconds
    try:
        logger.debug(f"waiting for slirp4netns readiness on fd {ready_fd}...")
        ready, _, _ = select.select([ready_fd], [], [], slirp_timeout)
        if not ready:
            logger.error(
                "Timed out waiting for slirp4netns readiness on fd %d after %ds",
                ready_fd,
                slirp_timeout,
            )
            print(
                f"ERROR: slirp4netns readiness timeout after {slirp_timeout}s",
                file=sys.stderr,
            )
            sys.exit(1)
        data = os.read(ready_fd, 1)
        logger.debug(f"slirp4netns readiness received: {data!r}")
        os.close(ready_fd)
    except OSError as e:
        logger.debug(f"slirp4netns readiness fd {ready_fd} error: {e}")

    # --- A2. Ensure tap0 is up and default route via slirp gateway ---
    # slirp4netns -c configures tap0 (10.0.2.100/24), but in some environments (e.g. nested
    # container, CI) the default route is missing or tap0 is not ready immediately; add it
    # explicitly and retry so outbound traffic reaches the host.
    logger.debug("configure tap0 and default route:")
    for attempt in range(5):
        if attempt > 0:
            time.sleep(0.3)
        r = subprocess.run(
            ["ip", "link", "set", SLIRP_INTERFACE, "up"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            logger.debug(
                "ip link set tap0 up (attempt %s): %s",
                attempt + 1,
                r.stderr or r.stdout,
            )
            continue
        # Ensure tap0 has an IP (slirp4netns -c usually sets 10.0.2.100; if missing, set 10.0.2.15)
        r = subprocess.run(
            ["ip", "addr", "add", SLIRP_TAP_CIDR, "dev", SLIRP_INTERFACE],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0 and "File exists" not in (r.stderr or ""):
            logger.debug("ip addr add tap0: %s", r.stderr or r.stdout)
        r = subprocess.run(
            [
                "ip",
                "route",
                "add",
                "default",
                "via",
                SLIRP_GATEWAY,
                "dev",
                SLIRP_INTERFACE,
            ],
            capture_output=True,
            text=True,
        )
        if r.returncode == 0:
            break
        # "File exists" means route already there; success
        if r.stderr and "File exists" in r.stderr:
            break
        logger.debug("ip route add default (attempt %s): %s", attempt + 1, r.stderr or r.stdout)
    else:
        logger.warning("Could not add default route via %s after 5 attempts", SLIRP_GATEWAY)
    # Brief delay so the kernel/slirp stack is ready before we apply iptables and exec
    time.sleep(1.0)
    # Log current state (print so it appears even when logging is not configured)
    for cmd, label in [
        (["ip", "addr", "show"], "ip addr"),
        (["ip", "route", "show"], "ip route"),
    ]:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and r.stdout:
            for line in r.stdout.strip().splitlines():
                logger.info("  %s: %s", label, line)

    # --- B. Configure loopback ---
    logger.debug("configure loopback:")
    _run(["ip", "link", "set", "lo", "up"])
    _run(
        ["ip", "addr", "add", "127.0.0.1/8", "dev", "lo"],
        check=False,
        stderr=subprocess.DEVNULL,
    )  # May already exist

    # --- C. Apply iptables rules ---
    if config.dns_servers and config.netfilter_rules:
        logger.debug("Apply iptables rules:")
        rules_text = "\n".join(config.netfilter_rules)
        subprocess.run(
            ["/usr/sbin/iptables-restore"],
            input=rules_text,
            text=True,
            check=True,
        )

    # --- D. Create chroot root ---
    logger.debug("Create chroot root:")
    new_root = tempfile.mkdtemp()
    _run(["mount", "-t", "tmpfs", "none", new_root])
    for d in ["dev", "proc", "tmp", "etc", "home", "root"]:
        os.makedirs(os.path.join(new_root, d), exist_ok=True)
    # Sticky bit required for /tmp semantics
    os.chmod(os.path.join(new_root, "tmp"), 0o1777)

    # --- E. System mounts (SSL certs etc.) ---
    logger.debug("Mount SSL certs:")
    for cert_path in ["/etc/ssl", "/etc/pki", "/etc/ca-certificates"]:
        _mount_bind(cert_path, cert_path, new_root, readonly=True)

    # --- F. Mount current directory ---
    if config.current_dir:
        logger.debug("Mount current directory:")
        _mount_bind(config.current_dir, config.current_dir, new_root, readonly=False)

    # --- G. User-defined mounts ---
    logger.debug("User-defined mounts:")
    for src, dst in config.mounts_ro:
        _mount_bind(src, dst, new_root, readonly=True)
    for src, dst in config.mounts_rw:
        _mount_bind(src, dst, new_root, readonly=False)

    # --- G.2. Apply ignore overlays (mask paths with no-access placeholder) ---
    if config.ignore_paths and config.current_dir:
        logger.debug("Apply ignore overlays:")
        prefix = config.current_dir.rstrip("/") + "/"
        for rel_path in config.ignore_paths:
            rel_path = rel_path.lstrip("/")
            # Path in chroot = new_root + current_dir + rel_path (current_dir can be absolute)
            full_in_chroot = os.path.normpath(new_root + prefix + rel_path)
            if not _is_reachable_in_chroot(full_in_chroot, new_root):
                logger.debug("ignore path %s does not resolve inside the chroot, skip", full_in_chroot)
                continue
            try:
                if os.path.isfile(full_in_chroot):
                    fd, placeholder = tempfile.mkstemp(dir=os.path.join(new_root, "tmp"))
                    os.close(fd)
                    os.chmod(placeholder, 0o000)
                    _run(["mount", "--bind", placeholder, full_in_chroot])
                else:
                    placeholder = tempfile.mkdtemp(dir=os.path.join(new_root, "tmp"))
                    os.chmod(placeholder, 0o000)
                    _run(["mount", "--bind", placeholder, full_in_chroot])
            except Exception as e:
                logger.warning("Could not overlay ignore path %s: %s", full_in_chroot, e)

    # --- H. Pseudo-filesystems ---
    logger.debug("Pseudo-filesystems:")
    dev_path = os.path.join(new_root, "dev")
    _run(["mount", "-t", "tmpfs", "-o", "mode=755,nosuid", "none", dev_path])
    for dev in ["null", "zero", "full", "random", "urandom", "tty"]:
        host_dev = f"/dev/{dev}"
        if os.path.exists(host_dev):
            target = os.path.join(dev_path, dev)
            Path(target).touch()
            _run(["mount", "--bind", host_dev, target])

    shm_path = os.path.join(dev_path, "shm")
    os.makedirs(shm_path, exist_ok=True)
    _run(["mount", "-t", "tmpfs", "-o", "mode=1777,nosuid,nodev", "tmpfs", shm_path])

    # Mount named pipe
    if config.named_pipe and os.path.exists(config.named_pipe):
        logger.debug("Mount named pipe:")
        pipe_dir = os.path.dirname(config.named_pipe)
        chroot_pipe_dir = new_root + pipe_dir
        chroot_pipe = new_root + config.named_pipe
        os.makedirs(chroot_pipe_dir, exist_ok=True)
        Path(chroot_pipe).touch()
        _run(["mount", "--bind", config.named_pipe, chroot_pipe])

    # --- I. DNS/hosts setup ---
    if config.dns_servers:
        logger.debug("DNS/hosts setup:")
        # Custom DNS: create resolv.conf and hosts
        resolv_tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".resolv")
        logger.debug(f"write dns {config.dns_servers=}")
        dns_servers = config.dns_servers
        for dns in dns_servers:
            resolv_tmp.write(f"nameserver {dns}\n")
        resolv_tmp.close()

        hosts_tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".hosts")
        hosts_tmp.write("127.0.0.1 localhost\n")
        for h in config.hosts:
            hosts_tmp.write(h + "\n")
        hosts_tmp.close()

        source_resolv = resolv_tmp.name
        source_hosts = hosts_tmp.name
    else:
        # Use host's config (resolve symlinks)
        source_resolv = os.path.realpath("/etc/resolv.conf")
        source_hosts = os.path.realpath("/etc/hosts")

    resolv_target = os.path.join(new_root, "etc", "resolv.conf")
    _ensure_mount_target(resolv_target, new_root)
    if os.path.exists(source_resolv):
        _run(["mount", "--bind", source_resolv, resolv_target])

    hosts_target = os.path.join(new_root, "etc", "hosts")
    _ensure_mount_target(hosts_target, new_root)
    if os.path.exists(source_hosts):
        _run(["mount", "--bind", source_hosts, hosts_target])

    # --- J. Enter sandbox (PID namespace + chroot) ---
    chroot_cmd = shutil.which("chroot") or "/usr/sbin/chroot"
    setpriv_cmd = shutil.which("setpriv") or "/usr/bin/setpriv"

    os.chdir(new_root)
    proc_path = os.path.join(new_root, "proc")

    # This stage needed the host environment -- PATH for mount/ip/iptables, and the
    # launcher's own PID_FILE and SLIRP_READY_FD -- but the sandbox must not inherit
    # any of it: ``execvp`` below would hand the parent's whole environment, API
    # tokens included, to the code being isolated. Everything above is done, so
    # narrow the environment to what the profile whitelists.
    #
    # PYTHONPATH survives because the daemon on the other side of the exec still has
    # to import pysandboxes (see the comment in unshare_sse_daemon.subprocess_cmd);
    # it names the project directory, which the sandbox can already see.
    preserved = {name: os.environ[name] for name in ("PYTHONPATH",) if name in os.environ}
    os.environ.clear()
    os.environ.update(config.sandbox_envs)
    os.environ.update(preserved)

    logger.debug("Enter in sandbox...")
    exec_args = [
        "/usr/bin/unshare",
        "-p",
        "-f",
        f"--mount-proc={proc_path}",
        chroot_cmd,
        new_root,
        "/usr/bin/env",
        f"--chdir={config.current_dir}",
        setpriv_cmd,
        "--inh-caps=-all",
        "--bounding-set=-all",
        "--",
        *command,
    ]
    os.execvp(exec_args[0], exec_args)


if __name__ == "__main__":
    if DEBUG:
        _debug_log()

    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        import traceback

        print(f"unshare_setup FATAL: {e}", file=sys.stderr, flush=True)
        traceback.print_exc()
        sys.exit(1)
