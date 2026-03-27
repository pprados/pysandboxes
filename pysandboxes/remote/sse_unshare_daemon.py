# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Unshare-based daemon for OS-level sandboxing.

This module implements a unshare-based sandbox daemon that uses
Linux namespaces directly via the `unshare` command, `slirp4netns`
for networking, and standard Linux tools (mount, iptables) for isolation.
"""

import logging
import os
import site
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, cast

from pysandboxes.remote.sse_client_subprocess_daemon import DEBUG_LAUNCH
from pysandboxes.remote.tools import suggest_package_installation

try:
    from typing import override  # type: ignore[attr-defined]
except ImportError:
    from typing_extensions import override

from ..all_rules import AllRules
from ..guard_files import BindRule, IgnoreRule
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg
from ..netfilter import rule_to_netfilter
from ..sb_types import Args, ConfigLines, Envs
from ..tools import Environ, remove_comments, substitute_env_vars
from .sse_client_subprocess_daemon import BaseSubProcessDaemon
from .tools import which_command

logger = logging.getLogger(__name__)


class UnshareSSEDaemon(BaseSubProcessDaemon):
    """Unshare-based subprocess daemon for OS-level sandboxing.

    Uses `unshare`, `slirp4netns`, `iptables`, and `mount` to create
    an isolated environment.
    """

    @override
    def parse_rules(
        self,
        rules: ConfigLines,
        errors: list[ErrorMsg],
    ) -> tuple[ImmutableDict[str, Any], ConfigLines]:
        unshare_params = {}
        ignore_rules: ConfigLines = []

        for rule in rules:
            if rule.rule.startswith("unshare."):
                param = rule.rule[len("unshare.") :]
                key, _, val = param.partition("=")
                unshare_params[key] = val
            else:
                ignore_rules.append(rule)
        return ImmutableDict(unshare_params), ignore_rules

    @override
    def update_rules(
        self,
        *,
        all_rules: AllRules,
        envs: Envs,
        temp: Path,
    ) -> AllRules:
        """Update rules for unshare context.

        Args:
            all_rules: Current security rules.
            envs: Environment variables.

        Returns:
            Updated security rules.
        """
        # We don't change the rules themselves, but we prepare the environment
        # in subprocess_cmd.
        return all_rules

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Build complete command line for unshare subprocess.

        Args:
            all_rules: Security rules configuration.
            envs: Environment variables.
            pipe_path: Path to configuration pipe.

        Returns:
            Complete command line arguments.
        """
        # 1. Verify availability
        unshare_cmd = which_command("unshare")
        if not unshare_cmd:
            logger.error("unshare not found.")
            sys.exit(1)

        # Verify sysctl kernel.unprivileged_userns_clone
        try:
            with open("/proc/sys/kernel/unprivileged_userns_clone", "r") as f:
                content = f.read().strip()
                if content != "1":
                    raise RuntimeError("kernel.unprivileged_userns_clone must be 1")
        except FileNotFoundError:
            # If the file doesn't exist, we assume it's capable (mainstream kernel)
            pass

        # 2. Prepare arguments
        import importlib.resources

        launch_sh_path: Path = (
            cast(
                Path,
                importlib.resources.files(
                    ".".join(__name__.rsplit(".", maxsplit=1)[:-1])
                ),
            )
            / ".."
            / "templates"
            / "./unshare_launch.sh"
        ).resolve()
        setup_sh_path: Path = (
            cast(
                Path,
                importlib.resources.files(
                    ".".join(__name__.rsplit(".", maxsplit=1)[:-1])
                ),
            )
            / ".."
            / "templates"
            / "./unshare_setup.sh"
        ).resolve()
        template_path: Path = (
            cast(
                Path,
                importlib.resources.files(
                    ".".join(__name__.rsplit(".", maxsplit=1)[:-1])
                ),
            )
            / ".."
            / "templates"
            / "unshare.template"
        ).resolve()
        if DEBUG_LAUNCH:
            netfilter_file = Path("iptables.rules")
        else:
            netfilter_file = temp / "iptables.rules"
            if netfilter_file.exists():
                netfilter_file.unlink()
            os.mkfifo(netfilter_file)

        # Load and fill unshare.sh template
        if DEBUG_LAUNCH:
            setup_file = Path("unshare_setup.sh")
        else:
            setup_file = temp / "unshare_setup.sh"
            os.mkfifo(setup_file)

        args = [str(launch_sh_path), str(setup_file.resolve())]

        # Load template

        template_conf = remove_comments(template_path.read_text().splitlines())
        envs["UID"] = str(os.getuid())
        envs["GID"] = str(os.getgid())
        template_conf = substitute_env_vars(template_conf, envs)

        for line in template_conf:
            args.extend(line.split())

        # Add custom params
        for k, v in all_rules.os_sandbox_params.items():
            if v:
                args.append(f"--{k}={v}")
            else:
                args.append(f"--{k}")

        # 3. Networking (IPTables)
        from ipaddress import IPv4Address

        from .tools import get_systemd_resolved_upstream_dns

        dns_servers = [
            ip
            for ip in get_systemd_resolved_upstream_dns()
            if isinstance(ip, IPv4Address)
        ]
        net_filter4 = rule_to_netfilter(
            all_rules.socket_rules, dns_servers, is_ipv6=False
        )

        # 4. Generate Setup Script and Netfilter via FIFOs
        # Build MOUNTS block
        mounts: set[tuple[str, str, bool]] = set()

        # System paths
        for p in ["/bin", "/usr", "/lib", "/lib64", "/etc"]:
            mounts.add((p, p, False))

        # Python environment
        python_paths = [sys.executable] + sys.path
        if hasattr(site, "getsitepackages"):
            python_paths += site.getsitepackages()

        for p in python_paths:
            if p and os.path.exists(p):
                mounts.add((p, p, False))

        # Ipython directory
        # ipython_path = str(Path("~/.ipython").expanduser())
        # mounts.add((p,p,True))

        # Rules from configuration
        for rule in all_rules.file_rules:
            if isinstance(rule, BindRule):
                dest = rule.dest if rule.dest is not None else rule.source
                mounts.add((rule.source, dest, rule.write))
            elif isinstance(rule, IgnoreRule):
                pass  # FIXME

        mounts_cmds = [f'mount_readonly  "{m[0]}" "{m[1]}"' for m in mounts if not m[2]]
        mounts_cmds += [f'mount_readwrite "{m[0]}" "{m[1]}"' for m in mounts if m[2]]

        setup_script_content = setup_sh_path.read_text().replace(
            "${PYSANDBOXES_MOUNTS}", "\n".join(mounts_cmds)
        )
        hosts = []  # FIXME
        setup_script_content = setup_script_content.replace(
            "${PYSANDBOXES_HOSTS}", "\n".join(hosts)
        )
        # Ensure the script uses the correct netfilter file path
        setup_script_content = setup_script_content.replace(
            "iptables.rules", str(netfilter_file)
        )

        def publish_setup() -> None:
            setup_file.write_text(setup_script_content)
            if not DEBUG_LAUNCH:
                try:
                    setup_file.unlink(missing_ok=True)
                except Exception:
                    pass

        def publish_netfilter() -> None:
            netfilter_file.write_text("\n".join(net_filter4))
            if not DEBUG_LAUNCH:
                try:
                    netfilter_file.unlink(missing_ok=True)
                except Exception:
                    pass

        threading.Thread(target=publish_setup, daemon=True).start()
        threading.Thread(target=publish_netfilter, daemon=True).start()

        # 5. Construct final command
        args.append("--")

        # Append the python command
        run_daemon_cmd, extra_envs = BaseSubProcessDaemon.subprocess_cmd(
            self,
            all_rules,
            envs,
            pipe_path,
            temp=temp,
        )
        args.extend(run_daemon_cmd)

        template_launch_sh_path: Path = (
            cast(
                Path,
                importlib.resources.files(
                    ".".join(__name__.rsplit(".", maxsplit=1)[:-1])
                ),
            )
            / ".."
            / "templates"
            / "unshare_launch.sh"
        )
        template_launch_sh_path = template_launch_sh_path.relative_to(Path.cwd())
        # args = ["/bin/bash", str(template_launch_sh_path)] + args
        # extra_envs = extra_envs | {
        #     "PYSANDBOXES_HOSTS": "1.2.3.4 my-test.local;8.8.8.8 dns.google",  # FIXME
        #     "PYSANDBOXES_MOUNTS": "mount_readonly /bin; mount_readonly /usr; mount_readonly /lib; mount_readonly /lib64"
        # }
        return args, extra_envs

    def _get_slirp4netns(self):
        slirp_cmd = which_command("slirp4netns")
        if not slirp_cmd:
            logger.error("slirp4netns not found. Install it with:")
            logger.error(suggest_package_installation("slirp4netns"))
            try:
                if self._process:
                    self._process.kill()
            except Exception:
                pass
            sys.exit(1)
        return slirp_cmd

    @override
    async def _on_process_started(self) -> None:
        """Start slirp4netns after the unshare process is created."""

        assert self._process
        slirp_cmd = self._get_slirp4netns()
        slirp_args = [
            str(slirp_cmd),
            "--configure",
            "--mtu=65520",
            "--disable-host-loopback",
            str(self._process.pid),
            "tap0",
        ]

        logger.debug("Starting slirp4netns: %s", slirp_args)
        self._slirp_process = subprocess.Popen(
            slirp_args,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    @override
    async def _stop(self, max_pending: int) -> None:
        await super()._stop(max_pending)
        if hasattr(self, "_slirp_process") and self._slirp_process:
            try:
                self._slirp_process.terminate()
                self._slirp_process.wait(timeout=1)
            except Exception:
                pass
