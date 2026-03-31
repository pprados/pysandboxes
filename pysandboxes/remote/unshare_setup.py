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
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

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
        )


def _run(cmd: list[str], check=True, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """Run a command, raising on failure."""
    logger.debug("  %s"," ".join(cmd))
    subprocess.run(cmd, check=check,**kwargs)


def _mount_bind(src: str, dst: str, new_root: str, readonly: bool) -> None:
    """Bind-mount src to new_root/dst, optionally read-only."""
    if not os.path.exists(src):
        logger.debug(f"mount {src=} not exist")
        return
    full_dst = new_root + dst
    logger.debug(f"mount {full_dst=}")
    if os.path.isdir(src):
        os.makedirs(full_dst, exist_ok=True)
    else:
        os.makedirs(os.path.dirname(full_dst), exist_ok=True)
        if not os.path.exists(full_dst):
            Path(full_dst).touch()
    _run(["mount", "--rbind", src, full_dst])
    if readonly:
        _run(["mount", "-o", "remount,ro,bind,nosuid,nodev", full_dst])
    logger.debug(f"")


def _ensure_mount_target(target: str, new_root: str) -> None:
    """Ensure a mount target exists, resolving symlinks within the chroot."""
    if os.path.islink(target):
        link_target = os.readlink(target)
        if link_target.startswith("/"):
            resolved = new_root + link_target
        else:
            resolved = os.path.normpath(
                os.path.join(os.path.dirname(target), link_target)
            )
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        Path(resolved).touch()
    elif not os.path.exists(target):
        os.makedirs(os.path.dirname(target), exist_ok=True)
        Path(target).touch()


def main() -> None:
    """Entry point for unshare_setup, called as `python -m pysandboxes.remote.unshare_setup`."""
    # Usage: python -m ... <config_path> -- <command> [args...]
    logger.debug("************* unshare_setup")
    args = sys.argv[1:]
    if not args:
        print(
            "Usage: unshare_setup <config_path> -- <command> [args...]", file=sys.stderr
        )
        sys.exit(1)

    config_path = args[0]
    # Find separator
    if "--" in args:
        sep_idx = args.index("--")
        command = args[sep_idx + 1 :]
    else:
        command = args[1:]

    # Read configuration
    logger.debug(f"load config ...")
    txt_config=Path(config_path).read_text()
    config = UnshareSetupConfig.from_json(txt_config)
    logger.debug(f"config loader {txt_config}")
    logger.debug(f"config dns {config.dns_servers}")

    # --- A. Signal readiness and wait for network ---
    pid_file = os.environ.get("PID_FILE", "")
    logger.debug(f"{pid_file=}")
    if pid_file:
        Path(pid_file).write_text(str(os.getpid()))

    # Wait for slirp4netns readiness on fd 3
    try:
        os.read(3, 1)
        os.close(3)
    except OSError:
        pass

    # --- B. Configure loopback ---
    _run(["ip", "link", "set", "lo", "up"])
    _run(
        ["ip", "addr", "add", "127.0.0.1/8", "dev", "lo"],
        check=False,
        stderr=subprocess.DEVNULL,
    )  # May already exist
    logger.debug("configure loopback done")

    # --- C. Apply iptables rules ---
    # FIXME
    # if config.dns_servers and config.netfilter_rules:
    #     rules_text = "\n".join(config.netfilter_rules)
    #     subprocess.run(
    #         ["/usr/sbin/iptables-restore"],
    #         input=rules_text,
    #         text=True,
    #         check=True,
    #     )
    # logger.debug("Apply iptables rules done")

    # --- D. Create chroot root ---
    new_root = tempfile.mkdtemp()
    _run(["mount", "-t", "tmpfs", "none", new_root])
    for d in ["dev", "proc", "tmp", "etc", "home", "root"]:
        os.makedirs(os.path.join(new_root, d), exist_ok=True)
    os.chmod(os.path.join(new_root, "tmp"), 0o1777)
    logger.debug("Create chroot root done")

    # --- F. Mount current directory ---
    if config.current_dir:
        _mount_bind(config.current_dir, config.current_dir, new_root, readonly=False)
        logger.debug("Mount current directory done")

    # --- G. User-defined mounts ---
    for src, dst in config.mounts_ro:
        _mount_bind(src, dst, new_root, readonly=True)
    for src, dst in config.mounts_rw:
        _mount_bind(src, dst, new_root, readonly=False)
    logger.debug("User-defined mounts done")

    # --- E. System mounts (SSL certs etc.) ---
    for cert_path in ["/etc/ssl", "/etc/pki", "/etc/ca-certificates"]:
        _mount_bind(cert_path, cert_path, new_root, readonly=True)
    logger.debug("System mounts done")


    # --- H. Pseudo-filesystems ---
    dev_path = os.path.join(new_root, "dev")
    _run(["mount", "-t", "tmpfs", "-o", "mode=755,nosuid", "none", dev_path])
    for dev in ["null", "zero", "full", "random", "urandom", "tty"]:
        host_dev = f"/dev/{dev}"
        if os.path.exists(host_dev):
            target = os.path.join(dev_path, dev)
            Path(target).touch()
            _run(["mount", "--bind", host_dev, target])
    logger.debug("Pseudo-filesystems done")

    shm_path = os.path.join(dev_path, "shm")
    os.makedirs(shm_path, exist_ok=True)
    _run(["mount", "-t", "tmpfs", "-o", "mode=1777,nosuid,nodev", "tmpfs", shm_path])

    # Mount named pipe
    if config.named_pipe and os.path.exists(config.named_pipe):
        pipe_dir = os.path.dirname(config.named_pipe)
        chroot_pipe_dir = new_root + pipe_dir
        chroot_pipe = new_root + config.named_pipe
        os.makedirs(chroot_pipe_dir, exist_ok=True)
        Path(chroot_pipe).touch()
        _run(["mount", "--bind", config.named_pipe, chroot_pipe])
    logger.debug("Mount named pipe done")

    # --- I. DNS/hosts setup ---
    # if config.dns_servers:
    #     # Custom DNS: create resolv.conf and hosts
    #     resolv_tmp = tempfile.NamedTemporaryFile(
    #         mode="w", delete=False, suffix=".resolv"
    #     )
    #     logger.debug(f"write dns {config.dns_servers=}")
    #     for dns in config.dns_servers:
    #         resolv_tmp.write(f"nameserver {dns}\n")
    #     resolv_tmp.close()
    #
    #     hosts_tmp = tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".hosts")
    #     hosts_tmp.write("127.0.0.1 localhost\n")
    #     for h in config.hosts:
    #         hosts_tmp.write(h + "\n")
    #     hosts_tmp.close()
    #
    #     source_resolv = resolv_tmp.name
    #     source_hosts = hosts_tmp.name
    # else:
    #     # Use host's config (resolve symlinks)
    #     source_resolv = os.path.realpath("/etc/resolv.conf")
    #     source_hosts = os.path.realpath("/etc/hosts")
    # logger.debug("DNS/hosts setup step 1")
    source_resolv = os.path.realpath("/etc/resolv.conf") # FIXME
    source_hosts = os.path.realpath("/etc/hosts")  # FIXME

    resolv_target = os.path.join(new_root, "etc", "resolv.conf")
    _ensure_mount_target(resolv_target, new_root)
    if os.path.exists(source_resolv):
        _run(["mount", "--bind", source_resolv, resolv_target])

    hosts_target = os.path.join(new_root, "etc", "hosts")
    _ensure_mount_target(hosts_target, new_root)
    if os.path.exists(source_hosts):
        _run(["mount", "--bind", source_hosts, hosts_target])
    logger.debug("DNS/hosts setup done")

    # --- J. Enter sandbox (PID namespace + chroot) ---
    chroot_cmd = shutil.which("chroot") or "/usr/sbin/chroot"
    setpriv_cmd = shutil.which("setpriv") or "/usr/bin/setpriv"

    os.chdir(new_root)
    proc_path = os.path.join(new_root, "proc")

    logger.debug("enter sandbox...")
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
        "/usr/bin/bash"
        # FIXME *command,
    ]
    os.execvp(exec_args[0], exec_args)
    logger.debug("enter sandbox done")

def test_raw_dns(server: str = "8.8.8.8") -> None:
    print(f"Testing raw UDP connection to {server}:53...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2)
    try:
        # On n'envoie rien, on teste juste si le port est atteignable
        sock.connect((server, 53))
        print("Successfully connected (UDP port reachable).")
    except Exception as e:
        print(f"Connection failed: {e}")
    finally:
        sock.close()


if __name__ == "__main__":
    _debug_log()  # FIX_RELEASE
    # Path("/tmp/toto").mkdir(exist_ok=True)
    # _mount_bind("/etc","/etc","/tmp/toto",readonly=True)
    import socket
    resolv=Path("/etc/resolv.conf").read_text()
    logger.debug("resolv au debut")
    logger.debug(resolv)

    main()
