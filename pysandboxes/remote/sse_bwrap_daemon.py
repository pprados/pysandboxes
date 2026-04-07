# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Bubblewrap (bwrap) based daemon for OS-level sandboxing with PySandboxes.

This module implements a bwrap-based sandbox daemon that combines
PySandboxes Python-level security with bubblewrap OS-level isolation.
It loads a bwrap template, translates file rules to bind mounts,
and launches the sandboxed Python process. First iteration uses
localhost for base_url (no network namespace).
"""

import fnmatch
import importlib.resources
import logging
import os
import shlex
import site
import sys
from pathlib import Path
from typing import Any, cast

from ..all_rules import AllRules
from ..guard_files import BindRule, IgnoreRule
from ..immutable_dict import ImmutableDict
from ..main_logger import ErrorMsg
from ..override_compat import override
from ..sb_types import Args, ConfigLines, Envs
from ..tools import (
    Environ,
    follow_links_executable,
    remove_comments,
    substitute_env_vars,
)
from .sse_client_subprocess_daemon import BaseSubProcessDaemon
from .tools import suggest_package_installation, which_command

logger = logging.getLogger(__name__)


def _resolve_ignore_paths(
    current_dir: str,
    ignore_rules: list[IgnoreRule],
) -> list[str]:
    """Resolve ignore rules to paths relative to current_dir (same semantics as unshare)."""
    if not ignore_rules:
        return []
    patterns = [r.source for r in ignore_rules]
    result: list[str] = []
    try:
        cur = Path(current_dir).resolve()
        for root, _dirs, files in os.walk(cur):
            root_path = Path(root)
            for name in list(_dirs) + files:
                if any(fnmatch.fnmatch(name, p) for p in patterns):
                    rel = root_path / name
                    try:
                        rel = rel.relative_to(cur)
                    except ValueError:
                        continue
                    result.append(str(rel))
    except OSError:
        pass
    return result


class BWrapSSEDaemon(BaseSubProcessDaemon):
    """Bubblewrap-based subprocess daemon for OS-level sandboxing.

    Translates PySandboxes rules to bwrap arguments and launches
    sandboxed processes. First iteration: no network namespace; base_url
    is http://localhost:{PORT}.
    """

    @override
    def parse_rules(
        self,
        rules: ConfigLines,
        errors: list[ErrorMsg],
    ) -> tuple[ImmutableDict[str, Any], ConfigLines]:
        """Parse config lines: bwrap.* → os_sandbox_params, rest passed through."""
        bwrap_params: dict[str, str] = {}
        other_rules: ConfigLines = []

        for rule in rules:
            if rule.rule.startswith("bwrap."):
                param = rule.rule[len("bwrap.") :]
                key, _, val = param.partition("=")
                bwrap_params[key] = val
            else:
                other_rules.append(rule)
        return ImmutableDict(bwrap_params), other_rules

    @override
    def update_rules_and_activate(
        self,
        *,
        all_rules: AllRules,
        envs: Envs,
        temp: Path,
    ) -> AllRules:
        """No rule replacement for bwrap; return rules unchanged."""
        return all_rules

    @property
    @override
    def base_url(self) -> str:
        """First iteration: localhost only (no network namespace)."""
        return "http://localhost:{PORT}"

    def _bwrap_args(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> Args:
        """Build bwrap command arguments from template and rules."""
        bwrap_cmd = which_command("bwrap")
        if bwrap_cmd is None:
            logger.error("bwrap not found. Install it with:")
            logger.error(suggest_package_installation("bubblewrap"))
            sys.exit(1)

        args: Args = [str(bwrap_cmd)]

        # Load template (pysandboxes.templates)
        template_path: Path = (
            cast(
                Path,
                importlib.resources.files("pysandboxes"),  # type: ignore[attr-defined]
            )
            / "templates"
            / "bwrap.template"
        ).resolve()
        template_lines = remove_comments(template_path.read_text().splitlines())
        template_lines = substitute_env_vars(template_lines, envs)
        for line in template_lines:
            args.extend(shlex.split(line))

        # Profile env vars so the child sees TERM, My_ENV, etc. (template uses --clearenv)
        for k, v in all_rules.envs.items():
            args.extend(["--setenv", k, str(v)])

        # Share network so DNS and socket rules can be used (Python guard still restricts hosts)
        args.extend(["--share-net"])
        # Optional bwrap.* params (e.g. unshare-net to override)
        for k, v in all_rules.os_sandbox_params.items():
            if v:
                args.append(f"--{k}={v}")
            else:
                args.append(f"--{k}")

        # Minimal binds: /usr, /etc, /run (for resolv.conf when it points into /run)
        args.extend(["--ro-bind", "/usr", "/usr"])
        args.extend(["--ro-bind", "/etc", "/etc"])
        if Path("/run").is_dir():
            args.extend(["--ro-bind", "/run", "/run"])
        for lib_dir in ("/lib", "/lib64"):
            if Path(lib_dir).is_dir():
                args.extend(["--ro-bind", lib_dir, lib_dir])

        # Python executable and libraries: bind venv/prefix and resolved binary
        # so that symlinks like .venv/bin/python3 -> python -> /opt/conda/bin/python3.13 work
        bin_paths: set[Path] = set()
        follow_links_executable(Path(sys.executable), bin_paths)
        for p in bin_paths:
            args.extend(["--ro-bind", str(p), str(p)])
        resolved_exe = Path(sys.executable).resolve(strict=True)
        if resolved_exe not in bin_paths and not any(
            p in resolved_exe.parents for p in bin_paths
        ):
            args.extend(["--ro-bind", str(resolved_exe), str(resolved_exe)])
        for sp in sys.path:
            if sp and os.path.isdir(sp):
                args.extend(["--ro-bind", sp, sp])
        if hasattr(site, "getsitepackages"):
            for sp in site.getsitepackages():
                if sp and os.path.isdir(sp):
                    args.extend(["--ro-bind", sp, sp])

        # File rules: apply ro-bind first, then bind so writable mounts override
        for rule in all_rules.file_rules:
            if isinstance(rule, BindRule) and not rule.write:
                dest = rule.dest if rule.dest is not None else rule.source
                args.extend(["--ro-bind", rule.source, dest])
        for rule in all_rules.file_rules:
            if isinstance(rule, BindRule) and rule.write:
                dest = rule.dest if rule.dest is not None else rule.source
                args.extend(["--bind", rule.source, dest])

        # Temp dir so child can read the config pipe
        temp_str = str(temp)
        if temp_str:
            args.extend(["--bind", temp_str, temp_str])

        # Overlay ignore paths (e.g. .env) so they are not visible in the sandbox
        ignore_rules = [r for r in all_rules.file_rules if isinstance(r, IgnoreRule)]
        current_dir = os.getcwd()
        ignore_paths = _resolve_ignore_paths(current_dir, ignore_rules)
        for i, rel_path in enumerate(ignore_paths):
            full_host = os.path.normpath(os.path.join(current_dir, rel_path))
            if not os.path.exists(full_host):
                continue
            try:
                if os.path.isfile(full_host):
                    placeholder = temp / f"pysb_ignore_{i}"
                    placeholder.touch()
                else:
                    placeholder = temp / f"pysb_ignore_{i}"
                    placeholder.mkdir(exist_ok=True)
                args.extend(["--bind", str(placeholder), full_host])
            except OSError as e:
                logger.debug(
                    "Could not create overlay for ignore path %s: %s", full_host, e
                )

        return args

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Build full command: bwrap [args] -- python -m pysandboxes.remote.main_sandbox ..."""
        inner_cmd, extra_env = super().subprocess_cmd(
            all_rules, envs, pipe_path, temp=temp
        )
        bwrap_args = self._bwrap_args(
            all_rules=all_rules, envs=dict(envs), pipe_path=pipe_path, temp=temp
        )
        bwrap_args.append("--")
        bwrap_args.extend(inner_cmd)
        return bwrap_args, extra_env
