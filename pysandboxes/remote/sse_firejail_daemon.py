# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Firejail-based daemon for OS-level sandboxing with PySandboxes.

This module implements a firejail-based sandbox daemon that combines
PySandboxes Python-level security with firejail OS-level isolation.
It configures firejail profiles, manages file system access rules,
and handles network filtering for comprehensive sandboxing.

Key components:
- WhiteList: Optimized directory path whitelist management
- FireJailSSEDaemon: Firejail subprocess daemon implementation
- Firejail profile generation and rule translation
"""

import importlib
import ipaddress
import logging
import os
import re
import shlex
import site
import subprocess
import sys
import tempfile
import threading
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any, Iterator, MutableSet, cast

from ..all_rules import AllRules
from ..guard_files import BindRule, IgnoreRule
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg
from ..netfilter import rule_to_netfilter
from ..sb_types import Args, ConfigLine, ConfigLines, Envs
from ..tools import (
    Environ,
    follow_links_executable,
    remove_comments,
    substitute_env_vars,
)
from .sse_client_subprocess_daemon import BaseSubProcessDaemon
from .tools import (
    get_bridge_interfaces,
    get_default_interface,
    get_systemd_resolved_upstream_dns,
    suggest_package_installation,
    which_command,
)

logger = logging.getLogger(__name__)

DEBUG_NETFILTER = True  # DEBUG

USE_WHITELIST = True  # FIXME: rename whitelist

# Replace rules to delegate the filter to firejail.
# The exception are different
REPLACE = False  # FIXME


class WhiteList(MutableSet):
    """Optimized whitelist for directory paths with prefix logic.

    This class manages directory paths efficiently by applying prefix rules:
    - If a new path is already covered by an existing parent path, it's not added
    - If a new path covers existing child paths, the children are removed
    - Ensures minimal set of paths that cover all allowed directories
    """

    def __init__(self) -> None:
        """Initialize empty WhiteList."""
        self._set: set[str] = set()

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

    def __iter__(self) -> Iterator[str]:
        """Iterate over whitelisted directory paths.

        Returns:
            Iterator over directory paths.
        """
        return iter(self._set)

    def __len__(self) -> int:
        """Get number of whitelisted paths.

        Returns:
            Number of paths in the whitelist.
        """
        return len(self._set)

    def add(self, directory: str) -> None:
        """Add directory path to whitelist with prefix optimization.

        Args:
            directory: Directory path to add.
        """
        # Ensure the path ends with a separator to simplify prefix checks.
        if not directory.endswith("/"):
            directory += "/"

        # Check if an existing directory already prefixes the new one.
        for existing_dir in self._set:
            if directory.startswith(existing_dir):
                return

        # Find existing directories that are prefixed by the new directory.
        to_remove = {
            existing_dir
            for existing_dir in self._set
            if existing_dir.startswith(directory)
        }

        # If any directories are to be removed, perform the replacement.
        if to_remove:
            self._set -= to_remove
            self._set.add(directory)
        else:
            # If no replacements are needed, just add the new directory.
            self._set.add(directory)

    def discard(self, directory: str) -> None:
        """Remove directory path from whitelist.

        Args:
            directory: Directory path to remove.
        """
        # Ensure the path ends with a separator for consistency.
        if not directory.endswith("/"):
            directory += "/"
        self._set.discard(directory)


def _follow_links(filename: str | Path, whitelist: WhiteList) -> None:
    """Add file path and its symlink target to whitelist.

    Args:
        filename: File or directory path to add.
        whitelist: WhiteList to add paths to.

    Raises:
        RuntimeError: If symlink cannot be resolved.
    """
    whitelist.add(str(filename))
    try:
        if Path(filename).is_symlink():
            whitelist.add(str(Path(filename).resolve(strict=True)))
    except FileNotFoundError as e:
        raise RuntimeError(
            "Impossible to resolve the sys.executable `%s`", sys.executable
        ) from e


# Use firejail --ip.print to return the ip of the daemon with a specific pid
def get_firejail_daemon_ip(pid: int) -> ipaddress.IPv4Address:
    """
    Retrieves the IP address of a Firejail-isolated daemon using the 'firejail --net.print' command.

    Args:
        pid: The Process ID (PID) of the Firejail parent process to query.

    Returns:
        The IP address (str) of the daemon's isolated network interface,
        or None if the command fails or the IP is not found.
    """
    if not isinstance(pid, int) or pid <= 0:
        raise ValueError(f"Invalid PID provided: {pid}")

    try:
        # 1. Execute the firejail command.
        # --ip.print <pid> queries the network namespace for the specified PID.
        firejail_cmd = which_command("firejail")
        if firejail_cmd is None:
            logger.error("firejail not found. Install it with:")
            logger.error(suggest_package_installation("firejail"))
            raise SystemExit(1)
        command: list[str] = [str(firejail_cmd), f"--net.print={pid}"]

        # Capture stdout and stderr, timeout if it takes too long.
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,  # We handle the error manually
            timeout=2,
        )

        # 2. Check for command execution errors.
        if result.returncode != 0:
            logger.error("firejail error: %s", result.stderr.strip())
            raise SystemExit(1)

        # 3. Parse the output to find the IP address.
        output: str = result.stderr.strip()

        # The output format is typically: "IP address: <IP>" or just the IP.
        # We use a regex to reliably find an IPv4 address.
        # Regex explanation: (\d{1,3}\.){3}\d{1,3} matches four groups of 1-3 digits separated by dots.
        for line in output.split("\n"):
            parts: list[str] = line.split()
            if len(parts) > 2 and parts[0] == "eth0":
                return ipaddress.IPv4Address(parts[2])
        logger.error("firejail error: %s", result.stderr.strip())
        raise SystemExit(1)

    except FileNotFoundError as e:
        # firejail command is not in the system PATH.
        logger.error("firejail not found. Install it with:")
        logger.error(suggest_package_installation("firejail"))
        raise SystemExit(1) from e
    except subprocess.TimeoutExpired as e:
        # Command took longer than the timeout.
        logger.error(f"firejail command timed out for PID {pid}.")
        raise RuntimeError(f"firejail command timed out for PID {pid}.") from e
    except Exception as e:
        # Catch any other unexpected error.
        logger.error(f"with firejail command, an unexpected error occurred: {e}.")
        raise RuntimeError(
            f"with firejail command, an unexpected error occurred: {e}."
        ) from e


class FireJailSSEDaemon(BaseSubProcessDaemon):
    """Firejail-based subprocess daemon for OS-level sandboxing.

    Translates PySandboxes rules to firejail configuration and launches
    sandboxed processes with comprehensive OS-level isolation.
    """

    def parse_rules(
        self,
        rules: ConfigLines,
        errors: list[ErrorMsg],
    ) -> tuple[ImmutableDict[str, Any], ConfigLines]:
        firejail_params = {}
        net: str | None = None
        ignore_rules = []

        for rule in rules:
            if rule.rule.startswith("firejail."):
                firejail_param = rule.rule[len("firejail.") :]
                if firejail_param.startswith("net="):
                    net = firejail_param.split("=")[1]
                    # TODO: check net?
            else:
                ignore_rules.append(rule)
        if net:
            firejail_params["net"] = net
        return ImmutableDict(firejail_params), ignore_rules

    def update_rules(
        self,
        *,
        all_rules: AllRules,
        envs: Envs,
    ) -> AllRules:
        """Update rules by translating to firejail configuration.

        Args:
            all_rules: Current security rules.
            envs: Environment variables.

        Returns:
            Updated security rules for firejail context.
        """
        _, updated_all_rules = self._firejail_args(all_rules, envs, None)
        return updated_all_rules

    @property
    def base_url(self) -> str:
        assert self._process
        return f"http://{get_firejail_daemon_ip(self._process.pid)}:{{PORT}}"

    def _firejail_args(
        self,
        all_rules: AllRules,
        envs: Environ | Envs,
        pipe_path: Path | None,
    ) -> tuple[Args, AllRules]:
        """Generate firejail command arguments from PySandboxes rules.

        Args:
            all_rules: Security rules to translate.
            envs: Environment variables.
            pipe_path: Path to configuration pipe.

        Returns:
            Tuple of (firejail_args, updated_rules).
        """

        # Replace the rules.
        # The code never raise a RuleError
        if not which_command("firejail"):
            logger.error("firejail not found. Install it with:")
            logger.error(suggest_package_installation("firejail"))
            sys.exit(1)
        firejail_config = Path("/etc/firejail/firejail.config")
        restricted_network = True
        if firejail_config.exists():
            for line in firejail_config.read_text().split("\n"):
                if re.match(r"restricted-network\s+no", line):
                    restricted_network = False
                    break

        need_root = False
        args = [str(which_command("firejail"))]

        if logger.getEffectiveLevel() > logging.INFO:
            args.append("--quiet")
        else:
            logger.debug(
                "Activate Firejail's output (to remove, "
                "change the level of this logger)"
            )

        # Add default parameters
        firejail_path = (
            importlib.resources.files(__name__)
            / ".."
            / "templates"
            / "firejail.template"
        )
        firejail_conf = remove_comments(firejail_path.read_text().splitlines())
        firejail_conf = substitute_env_vars(firejail_conf, envs)

        for line in firejail_conf:
            args.extend(shlex.split(line))

        # Extend mapping if the python version use some links
        major, minor, release_level, *_ = sys.version_info
        whitelist = WhiteList()

        # Manage sys.executable
        bin_path: set[Path] = set()
        follow_links_executable(Path(sys.executable), bin_path)
        for p in bin_path:
            _follow_links(p, whitelist)

        for sp in sys.path:
            if os.path.isdir(sp):
                if sp not in whitelist:
                    _follow_links(sp, whitelist)

        for sp in site.getsitepackages():
            if os.path.isdir(sp):
                if sp not in whitelist:
                    _follow_links(p, whitelist)

        # Add ignore files rules
        keep_files_rules = []
        for rule in filter(lambda x: isinstance(x, IgnoreRule), all_rules.file_rules):
            args.append(f"--blacklist={rule.source}")

        for white in whitelist:
            args.extend(
                [
                    f"--whitelist={white}",
                    f"--read-only={white}",
                ]
            )

        for rule in sorted(
            filter(
                lambda x: isinstance(x, BindRule),
                all_rules.file_rules,
            ),
            key=lambda x: len(x.source),
        ):
            rule = cast(BindRule, rule)
            if rule.source == rule.dest:
                if rule.write or rule.source not in whitelist:
                    if rule.source != "/tmp/":
                        args.append(f"--whitelist={rule.source}")
                    whitelist.add(rule.source)
            else:
                # Note: py-sandbox manage the alias
                whitelist.add(rule.source)
                keep_files_rules.append(rule)
                need_root = False
                args.append(f"--whitelist={rule.source}")
            if not rule.write:
                args.append(f"--read-only={rule.source}")
            else:
                args.append(f"--read-write={rule.source}")

        if REPLACE:  # FIXME
            from ..guard_files import parse_rules as files_parse_rules

            _new_files_rules, _ = files_parse_rules(
                [ConfigLine("bind=/,/", Path(), 0)], []
            )
            new_files_rules = cast(list[BindRule], _new_files_rules)
            selected_rules = [
                rule
                for rule in all_rules.file_rules
                if isinstance(rule, BindRule) and rule.source != rule.dest
            ]
            selected_rules.extend(new_files_rules)  # Respect the order
            all_rules = all_rules._replace(file_rules=tuple(selected_rules))

        # Add pipe_path rule
        # with --private-tmp, need more parameters
        if pipe_path:
            args.append(f"--mkdir={str(pipe_path)}")
            args.append(f"--whitelist={str(pipe_path)}")  # Must be a whitelist
            # args.append(f"--read-only={str(pipe_path)}")  # Must be a whitelist
            # args.append(f"--read-write={str(pipe_path)}")  # FIXME

        if all_rules.socket_rules:
            if restricted_network:
                logger.error(
                    "Set 'restricted_network no' in %s "
                    "to use firejail with networks rules.",
                    repr(str(firejail_config)),
                )
                sys.exit(1)

            dns_servers = [
                ip
                for ip in get_systemd_resolved_upstream_dns()
                if isinstance(ip, IPv4Address)
            ]

            if dns_servers:
                for dns in dns_servers:
                    if not dns.is_loopback:
                        # Change to other, because inside the firejail, the loopback is not accessible
                        for dns in dns_servers:
                            args.append(f"--dns={dns}")
                        break
            else:
                # FIXME: see https://github.com/netblue30/firejail/discussions/6931
                # for pin_dns in dns_server_v6:
                #     if not pin_dns.is_loopback:
                #         loopback_dns = True
                #         args.append(f"--pin_dns={pin_dns}")
                #         break
                pass
            default_interface = get_default_interface()
            bridges = get_bridge_interfaces()
            if not bridges:
                bridge = default_interface  # FIXME: c'est lors de l'update inside
                # raise ValueError("Impossible to find a bridge (br*). "
                #                  "Create a bridge to use firejail.")
            else:
                bridge = bridges[0]  # FIXME: take first is a good idea?
            if not default_interface:
                raise ValueError("Impossible to detect the default network interface")
            args.append(f"--net={bridge}")

            if pipe_path:  # Update rules?
                net_filter4 = rule_to_netfilter(
                    all_rules.socket_rules, dns_servers, is_ipv6=False
                )
                netfilter_tmp_file = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".fifo"
                )
                netfilter_file = Path(netfilter_tmp_file.name)
                netfilter_tmp_file.close()
                netfilter_file.unlink(missing_ok=True)
                if DEBUG_NETFILTER:
                    netfilter_file = Path("netfilter.net")
                else:
                    os.mkfifo(netfilter_file)

                def publich_netfilter() -> None:
                    netfilter_file.write_text("\n".join(net_filter4))
                    if not DEBUG_NETFILTER:
                        netfilter_file.unlink(missing_ok=True)

                threading.Thread(target=publich_netfilter, daemon=True).start()

                args.append(f"--netfilter={netfilter_file}")  # FIXME

                net_filter6 = rule_to_netfilter(
                    all_rules.socket_rules, [], is_ipv6=True
                )
                netfilter6_tmp_file = tempfile.NamedTemporaryFile(
                    delete=False, suffix=".fifo"
                )
                netfilter6_file = Path(netfilter_tmp_file.name)
                netfilter6_tmp_file.close()
                netfilter6_file.unlink(missing_ok=True)
                if DEBUG_NETFILTER:
                    netfilter6_file = Path("netfilter6.net")
                else:
                    os.mkfifo(netfilter6_file)

                def publich_netfilter6() -> None:
                    netfilter6_file.write_text("\n".join(net_filter6))
                    if not DEBUG_NETFILTER:
                        netfilter_file.unlink(missing_ok=True)

                threading.Thread(target=publich_netfilter6, daemon=True).start()
                args.append(f"--netfilter6={netfilter6_file}")

            # Remove redondant sockets rules
            if REPLACE:
                from ..guard_socket import parse_rules as socket_parse_rules

                new_socket_rules, *_ = socket_parse_rules(
                    [ConfigLine("net=ALLOW|*|*|*|*", Path(), 0)], []
                )
                all_rules = all_rules._replace(socket_rules=tuple(new_socket_rules))

            # Clean env variable
            args.extend(["env", "-i"])
            for env, val in all_rules.envs.items():
                args.append(f"{env}={val}")

            if need_root:
                logger.warning("Firejail needs root to run")

        return args, all_rules

    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
    ) -> list[str]:
        """Build complete command line for firejail subprocess.

        Args:
            all_rules: Security rules configuration.
            envs: Environment variables.
            pipe_path: Path to configuration pipe.

        Returns:
            Complete command line arguments including firejail and subprocess args.
        """
        run_daemon_cmd = super().subprocess_cmd(
            all_rules,
            envs,
            pipe_path,
        )

        cmd_parameters, _ = self._firejail_args(
            all_rules=all_rules, envs=envs, pipe_path=pipe_path
        )
        cmd_parameters.extend(run_daemon_cmd)
        return cmd_parameters
