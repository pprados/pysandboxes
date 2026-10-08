# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Firejail-based daemon for OS-level sandboxing with PySandboxes.

This module implements a firejail-based sandbox daemon that combines
PySandboxes Python-level security with firejail OS-level isolation.
It configures firejail profiles, manages file system access rules,
and handles network filtering for comprehensive sandboxing.

Key components:
- AllowList: Optimized directory path whitelist management
- FireJailSSEDaemon: Firejail subprocess daemon implementation
- Firejail profile generation and rule translation
"""

import importlib
import ipaddress
import logging
import os
import re
import shlex
import subprocess
import sys
import threading
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any, Iterator, MutableSet, cast

from ..all_rules import AllRules
from ..config import DEBUG
from ..e import SandBoxError
from ..guard_files import FSExposeRule, IgnoreRule
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg
from ..netfilter import rule_to_netfilter
from ..override_compat import override
from ..sb_types import Args, ConfigLine, ConfigLines, Envs
from ..tools import (
    Environ,
    follow_links_executable,
    remove_comments,
    substitute_env_vars,
)
from .client_subprocess_sse_daemon import BaseSubProcessDaemon
from .tools import (
    get_bridge_interfaces,
    get_upstream_dns,
    suggest_package_installation,
    which_command,
)

logger = logging.getLogger(__name__)

DEBUG_NETFILTER = DEBUG or False

# Replace rules to delegate the filter to firejail.
# Exceptions differ from unshare backend
REPLACE = False  # TODO: firejail

FIREJAIL_CONFIG = Path("/etc/firejail/firejail.config")


class AllowList(MutableSet[str]):
    """Optimized list for directory paths with prefix logic.

    This class manages directory paths efficiently by applying prefix rules:
    - If a new path is already covered by an existing parent path, it's not added
    - If a new path covers existing child paths, the children are removed
    - Ensures minimal set of paths that cover all allowed directories
    """

    def __init__(self) -> None:
        """Initialize empty AllowList."""
        super().__init__()
        self._set: set[str] = set()

    @override
    def __contains__(self, item: Any) -> bool:
        """Check if directory path is covered by whitelist.

        Args:
            item: The directory path to check.

        Returns:
            True if path is whitelisted or is subdirectory of whitelisted path.
        """

        # Ensure the path ends with a separator for consistent prefix checking.
        if not item.endswith("/"):
            item += "/"

        # Check if the item itself is in the set, or if an existing directory is
        # a prefix of the item. This means the item is a subdirectory of a
        # whitelisted path.
        for existing_dir in self._set:
            if item.startswith(existing_dir):
                return True

        return False

    @override
    def __iter__(self) -> Iterator[str]:
        """Iterate over whitelisted directory paths.

        Returns:
            Iterator over directory paths.
        """
        return iter(self._set)

    @override
    def __len__(self) -> int:
        """Get number of whitelisted paths.

        Returns:
            Number of paths in the whitelist.
        """
        return len(self._set)

    @override
    def add(self, value: str) -> None:
        """Add directory path to whitelist with prefix optimization.

        Args:
            value: Directory path to add. Named after `MutableSet.add`, whose
                signature this overrides.
        """
        # Ensure the path ends with a separator to simplify prefix checks.
        if not value.endswith("/"):
            value += "/"

        # Check if an existing directory already prefixes the new one.
        for existing_dir in self._set:
            if value.startswith(existing_dir):
                return

        # Find existing directories that are prefixed by the new directory.
        to_remove = {existing_dir for existing_dir in self._set if existing_dir.startswith(value)}

        # If any directories are to be removed, perform the replacement.
        if to_remove:
            self._set -= to_remove
            self._set.add(value)
        else:
            # If no replacements are needed, just add the new directory.
            self._set.add(value)

    @override
    def discard(self, value: str) -> None:
        """Remove directory path from whitelist.

        Args:
            value: Directory path to remove. Named after `MutableSet.discard`,
                whose signature this overrides.
        """
        # Ensure the path ends with a separator for consistency.
        if not value.endswith("/"):
            value += "/"
        self._set.discard(value)


def _follow_links(filename: Path, whitelist: AllowList) -> None:
    """Add file path and its symlink target to whitelist.

    Args:
        filename: File or directory path to add.
        whitelist: AllowList to add paths to.

    Raises:
        RuntimeError: If symlink cannot be resolved.
    """
    if str(filename).startswith("/usr/lib"):
        return
    whitelist.add(str(filename))
    try:
        if Path(filename).is_symlink():
            whitelist.add(str(Path(filename).resolve(strict=True)))
    except FileNotFoundError as e:
        raise RuntimeError("Impossible to resolve the sys.executable `%s`", sys.executable) from e


def parse_firejail_net_print(pid: int) -> ipaddress.IPv4Address | None:
    """Return eth0 IPv4 inside the jail for ``pid``, or None if not available yet.

    With ``--net=…``, the sandboxed daemon is reached at this address from the
    host; ``127.0.0.1`` is wrong. Does not log or exit on failure (for ping retry).
    """
    if not isinstance(pid, int) or pid <= 0:
        return None

    try:
        firejail_cmd = which_command("firejail")
        if firejail_cmd is None:
            return None
        command: list[str] = [str(firejail_cmd), f"--net.print={pid}"]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
        if result.returncode != 0:
            return None
        output: str = result.stderr.strip()
        for line in output.split("\n"):
            parts: list[str] = line.split()
            if len(parts) > 2 and parts[0] == "eth0":
                return ipaddress.IPv4Address(parts[2])
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        return None


class FireJailSSEDaemon(BaseSubProcessDaemon):
    """Firejail-based subprocess daemon for OS-level sandboxing.

    Translates PySandboxes rules to firejail configuration and launches
    sandboxed processes with comprehensive OS-level isolation.
    """

    @classmethod
    @override
    def unavailable_reason(cls) -> str | None:
        return None if which_command("firejail") else "firejail not installed"

    @override
    def parse_rules(
        self,
        rules: ConfigLines,
        errors: list[ErrorMsg],
    ) -> tuple[ImmutableDict[str, Any], ConfigLines]:
        firejail_params = {}
        net: str | None = None
        ignore_rules: ConfigLines = []

        for rule in rules:
            if rule.rule.startswith("firejail."):
                firejail_param = rule.rule[len("firejail.") :]
                if firejail_param.startswith("net="):
                    net = firejail_param.split("=")[1]
                    # TODO: check net?
                elif firejail_param.startswith("seccomp="):
                    firejail_params["seccomp"] = firejail_param.split("=")[1]
                elif firejail_param.startswith("seccomp.keep="):
                    firejail_params["seccomp.keep"] = firejail_param.split("=")[1]
                elif firejail_param.startswith("seccomp.block="):
                    firejail_params["seccomp.block"] = firejail_param.split("=")[1]
                elif firejail_param.startswith("rlimit-"):
                    key, _, value = firejail_param.partition("=")
                    firejail_params[key] = value

            else:
                ignore_rules.append(rule)
        if net:
            firejail_params["net"] = net
        return ImmutableDict(firejail_params), ignore_rules

    @override
    def update_rules_and_activate(
        self,
        *,
        all_rules: AllRules,
        envs: Envs,
        temp: Path,
    ) -> AllRules:
        """Update rules by translating to firejail configuration.

        Args:
            all_rules: Current security rules.
            envs: Environment variables.
            temp: Run-time directory shared with the sandbox, holding the
                config pipe and the generated netfilter files.

        Returns:
            Updated security rules for firejail context.
        """
        if REPLACE:
            _, updated_all_rules = self._firejail_args(all_rules, envs, None, temp=temp)
        return all_rules

    @property
    @override
    def base_url(self) -> str:
        assert self._process
        ip = parse_firejail_net_print(self._process.pid)
        # No --net (e.g. the stock 'restricted-network yes'): the daemon is on the loopback, as the ping found it.
        host = "127.0.0.1" if ip is None else str(ip)
        return f"http://{host}:{{PORT}}"

    @override
    def _ping_url(self, port: int) -> str:
        assert self._process is not None
        ip = parse_firejail_net_print(self._process.pid)
        # No isolated net / IP not ready yet: fall back to loopback (same as plain subprocess).
        host = "127.0.0.1" if ip is None else str(ip)
        return f"http://{host}:{port}/ping"

    @override
    def _sse_bind_host(self, args: Args) -> str:
        """Every interface with ``--net=<bridge>``: the host reaches the jail on its eth0, not on its loopback.

        Without ``--net`` the jail keeps the host network, and ``--net=none`` leaves only the loopback.
        """
        net = [arg for arg in args if arg.startswith("--net=")]
        return "0.0.0.0" if net and net[-1] != "--net=none" else "127.0.0.1"

    def _firejail_args(
        self,
        all_rules: AllRules,
        envs: Environ | Envs,
        pipe_path: Path | None,
        temp: Path,
    ) -> tuple[Args, AllRules]:
        """Generate firejail command arguments from PySandboxes rules.

        Args:
            all_rules: Security rules to translate.
            envs: Environment variables.
            pipe_path: Path to configuration pipe.
            temp: Run-time directory shared with the sandbox, where the
                netfilter files are written and which firejail must whitelist.

        Returns:
            Tuple of (firejail_args, updated_rules).
        """

        # Replace the rules.
        # The code never raise a RuleError
        if not which_command("firejail"):
            logger.error("firejail not found. Install it with:")
            logger.error(suggest_package_installation("firejail"))
            raise SandBoxError("firejail not found.")
        firejail_config = FIREJAIL_CONFIG
        restricted_network = True
        # True when the admin wrote 'restricted-network yes': tolerated, see below.
        restricted_network_explicit_yes = False
        if firejail_config.exists():
            for line in firejail_config.read_text().split("\n"):
                if re.match(r"restricted-network\s+no", line):
                    restricted_network = False
                    break
                if re.match(r"restricted-network\s+yes", line):
                    restricted_network_explicit_yes = True
                    break

        need_root = False
        args = [str(which_command("firejail"))]
        for k, v in all_rules.os_sandbox_params.items():  # type: ignore[attr-defined]
            args.append(f"--{k}={v}")

        if logger.getEffectiveLevel() > logging.INFO:
            args.append("--quiet")
        else:
            logger.debug(
                "Activate Firejail's output (to remove, " "change the level of the logger %s)",
                __name__,
            )

        # Add default parameters
        firejail_path: Path = (
            cast(
                Path,
                importlib.resources.files(  # type: ignore[attr-defined]
                    ".".join(__name__.rsplit(".", maxsplit=1)[:-1])
                ),
            )  # type: ignore[attr-defined]
            / ".."
            / "templates"
            / "firejail.template"
        )
        firejail_conf = remove_comments(firejail_path.read_text().splitlines())
        firejail_conf = substitute_env_vars(firejail_conf, envs)

        for line in firejail_conf:
            options = shlex.split(line)
            # A profile's firejail.rlimit-* replaces the template's default rather than repeating the option.
            if options and options[0].lstrip("-").split("=")[0] in all_rules.os_sandbox_params:
                continue
            args.extend(options)

        # Extend mapping if the python version use some links
        whitelist = AllowList()

        # Manage sys.executable
        bin_path: set[Path] = set()
        bin_path = follow_links_executable(Path(sys.executable), bin_path)  # FIXME
        for p in bin_path:
            _follow_links(p, whitelist)

        for sp in sys.path:
            if os.path.isdir(sp):
                if sp not in whitelist:
                    _follow_links(Path(sp), whitelist)

        import site

        for sp in site.getsitepackages():
            if os.path.isdir(sp):
                if sp not in whitelist:
                    _follow_links(Path(sp), whitelist)

        # Add ignore files rules
        for ignore_rule in (r for r in all_rules.file_rules if isinstance(r, IgnoreRule)):
            args.append(f"--blacklist={ignore_rule.source}")

        # Ensure temp dir is whitelisted so firejail can read netfilter fifos and config pipe
        if pipe_path:
            temp_str = str(pipe_path.parent)
            if temp_str and temp_str not in whitelist:
                whitelist.add(temp_str)

        for white in whitelist:
            args.extend(
                [
                    f"--whitelist={white}",
                    f"--read-only={white}",
                ]
            )

        # Paths that firejail rejects for --whitelist/--read-only (e.g. /etc in some versions)
        def _firejail_skip_path(path: str) -> bool:
            norm = path.rstrip("/") or "/"
            return norm == "/etc"

        for rule in sorted(
            (r for r in all_rules.file_rules if isinstance(r, FSExposeRule)),
            key=lambda x: len(x.path),
        ):
            skip_path = _firejail_skip_path(rule.path)
            if rule.write or rule.path not in whitelist:
                # Under /etc, --private-etc provides the entries: a --whitelist there puts a tmpfs over
                # /etc, and --dns then fails with "fs_resolvconf: mount: No such file or directory".
                # firejail mounts its own /proc and aborts on "invalid whitelist path /proc".
                if (
                    rule.path != "/tmp/"
                    and not skip_path
                    and not rule.path.startswith("/etc/")
                    and not rule.path.startswith("/proc/")
                ):
                    args.append(f"--whitelist={rule.path}")
                whitelist.add(rule.path)
            if not skip_path:
                if not rule.write:
                    args.append(f"--read-only={rule.path}")
                else:
                    args.append(f"--read-write={rule.path}")

        if REPLACE:
            from ..guard_files import parse_rules as files_parse_rules

            _new_files_rules, _ = files_parse_rules([ConfigLine("expose-rw=/", Path(), 0)], [])
            new_files_rules = cast(list[FSExposeRule], _new_files_rules)
            selected_rules: list[Any] = []
            selected_rules.extend(new_files_rules)
            all_rules = all_rules._replace(file_rules=tuple(selected_rules))

        # Add pipe_path rule
        # with --private-tmp, need more parameters
        if pipe_path:
            args.append(f"--mkdir={str(pipe_path)}")
            args.append(f"--read-only={str(pipe_path)}")

        if all_rules.socket_rules:
            # Without 'restricted-network no' a regular user only gets --net=none, which
            # would also cut the host from the daemon's SSE port. A missing line is refused.
            if restricted_network and not restricted_network_explicit_yes:
                logger.error(
                    "Set 'restricted-network no' in %s " "to use firejail with networks rules.",
                    repr(str(firejail_config)),
                )
                raise SandBoxError(f"Set 'restricted-network no' in {str(firejail_config)!r} to use network rules.")

            # An explicit 'restricted-network yes' is tolerated, as on a GitHub runner: the
            # jail then keeps the HOST network and the socket rules are enforced by the
            # Python layer only. Native code, ctypes or a subprocess can reach any address.
            skip_network_setup = restricted_network and restricted_network_explicit_yes
            if skip_network_setup:
                logger.warning(
                    "firejail config 'restricted-network yes' in %s: the sandbox keeps the host "
                    "network, socket rules are enforced by the Python layer only.",
                    repr(str(firejail_config)),
                )

            if not skip_network_setup:
                dns_servers = [ip for ip in get_upstream_dns() if isinstance(ip, IPv4Address)]

                if dns_servers:
                    for dns in dns_servers:
                        if not dns.is_loopback:
                            # Change to other, because inside the firejail, the loopback is not accessible
                            for dns in dns_servers:
                                args.append(f"--dns={dns}")
                            break
                else:
                    # TODO: see https://github.com/netblue30/firejail/discussions/6931
                    # for pin_dns in dns_server_v6:
                    #     if not pin_dns.is_loopback:
                    #         loopback_dns = True
                    #         args.append(f"--pin_dns={pin_dns}")
                    #         break
                    pass
                if "net" not in all_rules.os_sandbox_params:  # type: ignore[attr-defined]
                    bridges = get_bridge_interfaces()
                    if not bridges:
                        raise ValueError(
                            "Firejail socket rules require a host bridge; create one or set firejail.net explicitly"
                        )
                    # Search "docker*" else, the first bridge
                    for bridge in bridges:
                        if bridge.startswith("docker"):
                            break
                    else:
                        bridge = bridges[0]
                    logger.debug(f"Select bridge {bridges}")
                    args.append(f"--net={bridge}")

                # The sandbox now owns a network namespace, so firejail accepts
                # --x11=none, which also closes the abstract X11 socket that the
                # template's blacklist cannot reach.
                args.append("--x11=none")

                if pipe_path:  # Update rules?
                    net_filter4 = rule_to_netfilter(all_rules.socket_rules, dns_servers, is_ipv6=False)

                    if DEBUG_NETFILTER:
                        Path("tmp").mkdir(parents=True, exist_ok=True)
                        netfilter_file = Path("tmp/netfilter.net")
                    else:
                        netfilter_file = temp / "netfilter.net"
                        os.mkfifo(netfilter_file)

                    def publish_netfilter() -> None:
                        _ = netfilter_file.write_text("\n".join(net_filter4))
                        if not DEBUG_NETFILTER:
                            netfilter_file.unlink(missing_ok=True)

                    threading.Thread(target=publish_netfilter, daemon=True).start()

                    args.append(f"--netfilter={netfilter_file}")

                    net_filter6 = rule_to_netfilter(all_rules.socket_rules, [], is_ipv6=True)
                    if DEBUG_NETFILTER:
                        # tmp already created above for netfilter.net
                        netfilter6_file = Path("tmp/netfilter6.net")
                    else:
                        netfilter6_file = temp / "netfilter6.net"
                        os.mkfifo(netfilter6_file)

                    def publish_netfilter6() -> None:
                        _ = netfilter6_file.write_text("\n".join(net_filter6))
                        if not DEBUG_NETFILTER:
                            netfilter6_file.unlink(missing_ok=True)

                    threading.Thread(target=publish_netfilter6, daemon=True).start()
                    args.append(f"--netfilter6={netfilter6_file}")

            # Remove duplicate sockets rules
            if REPLACE:
                from ..guard_socket import parse_rules as socket_parse_rules

                new_socket_rules, *_ = socket_parse_rules([ConfigLine("net=ALLOW|*|*|*|*", Path(), 0)], [])
                all_rules = all_rules._replace(socket_rules=tuple(new_socket_rules))

        else:
            # No socket rule: no network at all, loopback only. Allowed to regular
            # users even under 'restricted-network yes'.
            if "net" not in all_rules.os_sandbox_params:  # type: ignore[attr-defined]
                args.append("--net=none")
            args.append("--x11=none")

        # Clean env variable
        # TODO: remove dependencies ?
        args.extend(["/usr/bin/env", "-i"])
        for env, val in all_rules.envs.items():  # type: ignore[attr-defined]
            args.append(f"{env}={val}")

        if need_root:
            logger.warning("Firejail needs root to run")

        return args, all_rules

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Build complete command line for firejail subprocess.

        Args:
            all_rules: Security rules configuration.
            envs: Environment variables.
            pipe_path: Path to configuration pipe.
            temp: Run-time directory shared with the sandbox, passed on to the
                subprocess command builder.

        Returns:
            Complete command line arguments including firejail and subprocess args.
        """
        run_daemon_cmd, extra_env = super().subprocess_cmd(
            all_rules,
            envs,
            pipe_path,
            temp=temp,
        )

        cmd_parameters, _ = self._firejail_args(all_rules=all_rules, envs=envs, pipe_path=pipe_path, temp=temp)
        cmd_parameters.extend(run_daemon_cmd)
        return cmd_parameters, {}
