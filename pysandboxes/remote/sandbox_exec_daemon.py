# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""macOS Seatbelt launcher using the deprecated ``sandbox-exec`` command."""

from __future__ import annotations

import logging
import os
import sys
from ipaddress import IPv4Network, IPv6Network
from pathlib import Path
from typing import Iterable

from ..all_rules import AllRules
from ..guard_files import FSExposeRule, IgnoreRule
from ..guard_socket import Action, Direction, Kind, SocketRule
from ..override_compat import override
from ..tools import Environ
from .client_subprocess_sse_daemon import BaseSubProcessDaemon

logger = logging.getLogger(__name__)

_SANDBOX_EXEC = "/usr/bin/sandbox-exec"
_SYSTEM_READ_PATHS = (
    "/System",
    "/usr/lib",
    "/usr/share",
    "/Library/Apple",
    "/private/etc",
    "/private/var/db/timezone",
    "/dev",
)
_MAX_PROFILE_PORTS = 4096


def _sbpl_string(value: str) -> str:
    """Quote a path as an SBPL string, preserving spaces and UTF-8 characters."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _glob_regex(pattern: str) -> str:
    """Translate the fnmatch wildcards used by ignore= to a whole-path regex."""
    result = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            result.append(".*")
        elif char == "?":
            result.append(".")
        elif char == "[":
            end = pattern.find("]", index + 1)
            if end >= 0:
                content = pattern[index + 1 : end]
                if content.startswith("!"):
                    content = "^" + content[1:]
                result.append("[" + content.replace("\\", "\\\\") + "]")
                index = end
            else:
                result.append(r"\[")
        elif char in r".\+(){}^$|":
            result.append("\\" + char)
        else:
            result.append(char)
        index += 1
    result.append("$")
    return "".join(result)


def _path(path: str) -> str:
    """Canonicalize a configured path and remove a directory's trailing separator."""
    return os.path.realpath(path.rstrip(os.sep) or os.sep)


def _symlink_directories(path: str) -> set[str]:
    """Return directory symlinks in an executable's path chain for Seatbelt grants."""
    current = os.path.abspath(path)
    aliases: set[str] = set()
    for _ in range(40):
        parts = Path(current).parts
        prefix = parts[0]
        for index, part in enumerate(parts[1:], start=1):
            prefix = os.path.join(prefix, part)
            if not os.path.islink(prefix):
                continue
            if os.path.isdir(prefix):
                aliases.add(prefix)
            target = os.readlink(prefix)
            if not os.path.isabs(target):
                target = os.path.join(os.path.dirname(prefix), target)
            current = os.path.join(target, *parts[index + 1 :])
            break
        else:
            return aliases
    return aliases


def _parent_paths(path: str) -> set[str]:
    """Return lexical parent directories needed to resolve a runtime path."""
    return {str(parent) for parent in Path(os.path.abspath(path)).parents if parent != parent.parent}


def _path_rule(action: str, path: str) -> str:
    return f"({action} (subpath {_sbpl_string(path)}))"


def _ignore_paths(rules: AllRules) -> Iterable[str]:
    exposed = [rule.path for rule in rules.file_rules if isinstance(rule, FSExposeRule)]
    for rule in rules.file_rules:
        if not isinstance(rule, IgnoreRule):
            continue
        if os.path.isabs(rule.source):
            yield os.path.normpath(rule.source)
        else:
            for parent in exposed:
                yield os.path.join(_path(parent), rule.source)


def _network_scope(rule: SocketRule) -> str:
    network: IPv4Network | IPv6Network = rule.mask.network
    if network.prefixlen == 0:
        return "*"
    if network.network_address.is_loopback:
        return "localhost"
    return "*"


def _network_ports(rule: SocketRule, *, deny: bool = False) -> tuple[str, ...]:
    ports = rule.mask.ports
    if isinstance(ports, range) and ports.start == 0 and ports.stop >= 65536:
        return ("*",)
    if 0 in ports:
        logger.warning("Seatbelt cannot grant port 0 or an ephemeral port; that portion of %r stays denied.", rule)
    ports = tuple(port for port in ports if port != 0)
    if len(ports) > _MAX_PROFILE_PORTS:
        logger.warning(
            "Seatbelt cannot safely expand %d ports from %r; this network rule stays denied.", len(ports), rule
        )
        return ("*",) if deny else ()
    return tuple(str(port) for port in ports)


def _deny_overlaps(allow: SocketRule, deny: SocketRule, scope: str, port: str, kind: Kind) -> bool:
    if kind not in deny.mask.kinds or not set(allow.directions) & set(deny.directions):
        return False
    denied_ports = _network_ports(deny, deny=True)
    if port != "*" and "*" not in denied_ports and port not in denied_ports:
        return False
    deny_scope = _network_scope(deny)
    return scope == "*" or deny_scope == "*" or scope == deny_scope


def _network_rules(rules: AllRules) -> list[str]:
    """Translate expressible socket rules to port-scoped Seatbelt network actions."""
    rendered: set[str] = set()
    allows = [rule for rule in rules.socket_rules if rule.action == Action.ALLOW]
    denies = [rule for rule in rules.socket_rules if rule.action == Action.DENY]
    for rule in allows:
        scope = _network_scope(rule)
        if scope == "*" and rule.mask.network.prefixlen != 0:
            message = (
                "Seatbelt cannot filter remote network hosts; net= host restrictions are widened to any host "
                "on the configured port. Native code can bypass the Python guard."
            )
            if not rules.use_py_sandbox:
                message += " py-sandbox=false disables that guard."
            logger.warning(message)
        for port in _network_ports(rule):
            for kind in rule.mask.kinds:
                if any(_deny_overlaps(rule, deny, scope, port, kind) for deny in denies):
                    continue
                proto = "tcp" if kind == Kind.TCP else "udp"
                if Direction.OUT in rule.directions:
                    rendered.add(f"(allow network-outbound (remote {proto} {_sbpl_string(f'{scope}:{port}')}))")
                    if kind == Kind.UDP and port == "53":
                        logger.warning(
                            "Seatbelt needs unrestricted local UDP receive permission for DNS replies; "
                            "py-sandbox=false leaves inbound UDP sources unfiltered."
                        )
                        rendered.add("(allow network-inbound (local udp))")
                if Direction.IN in rule.directions:
                    local_scope = scope
                    rendered.add(f"(allow network-bind (local {proto} {_sbpl_string(f'{local_scope}:{port}')}))")
                    rendered.add(f"(allow network-inbound (local {proto} {_sbpl_string(f'{local_scope}:{port}')}))")
    return sorted(rendered)


def _build_profile(
    all_rules: AllRules,
    *,
    temp_dir: Path,
    python_executable: str,
    python_paths: tuple[str, ...],
    sse_port: int,
) -> str:
    """Build an SBPL profile from file and socket rules plus Python runtime needs."""
    runtime_paths = {_path(p) for p in (*python_paths, os.path.dirname(python_executable), *_SYSTEM_READ_PATHS)}
    python_framework = Path(_path(python_executable)).parent.parent / "Python"
    if python_framework.is_file():
        runtime_paths.add(_path(str(python_framework)))
    symlink_directories = _symlink_directories(python_executable)
    runtime_paths.update(symlink_directories)
    read_paths = set(runtime_paths)
    read_paths.add(_path(str(temp_dir)))
    write_paths = {_path(str(temp_dir))}
    executable_paths = runtime_paths | {_path(python_executable)}
    metadata_paths = set(_parent_paths(python_executable)) | set(_parent_paths(_path(python_executable)))
    for path in symlink_directories:
        metadata_paths.update(_parent_paths(path))
    metadata_paths.difference_update(read_paths)
    for rule in all_rules.file_rules:
        if isinstance(rule, FSExposeRule):
            path = _path(rule.path)
            read_paths.add(path)
            if rule.write:
                write_paths.add(path)
        elif isinstance(rule, IgnoreRule):
            continue

    lines = [
        "(version 1)",
        '(import "system.sb")',
        "(deny default)",
        "(allow process*)",
    ]
    for path in sorted(read_paths):
        lines.extend(
            [
                _path_rule("allow file-read*", path),
                _path_rule("allow file-read-metadata", path),
                _path_rule("allow file-test-existence", path),
            ]
        )
    for path in sorted(metadata_paths):
        lines.extend(
            [
                _path_rule("allow file-read-metadata", path),
                _path_rule("allow file-test-existence", path),
            ]
        )
    for path in sorted(write_paths):
        lines.append(_path_rule("allow file-write*", path))
    for path in sorted(executable_paths):
        lines.append(_path_rule("allow file-map-executable", path))

    for pattern in _ignore_paths(all_rules):
        regex = _glob_regex(pattern)
        quoted = '#"' + regex.replace('"', '\\"') + '"'
        lines.append(f"(deny file-read* file-write* file-read-metadata file-test-existence (regex {quoted}))")

    lines.append("(deny network*)")
    lines.extend(_network_rules(all_rules))
    lines.append(f"(allow network-bind (local tcp {_sbpl_string(f'*:{sse_port}')}))")
    lines.append(f"(allow network-inbound (local tcp {_sbpl_string(f'*:{sse_port}')}))")
    return "\n".join(lines) + "\n"


class SandboxExecSSEDaemon(BaseSubProcessDaemon):
    """Launch the existing SSE daemon under a generated macOS Seatbelt profile."""

    @classmethod
    @override
    def unavailable_reason(cls) -> str | None:
        if sys.platform != "darwin":
            return "sandbox-exec is only available on macOS"
        if not os.path.isfile(_SANDBOX_EXEC) or not os.access(_SANDBOX_EXEC, os.X_OK):
            return f"{_SANDBOX_EXEC} is missing or not executable"
        return None

    @override
    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[list[str], Environ]:
        command, extra_envs = super().subprocess_cmd(all_rules, envs, pipe_path, temp)
        profile = _build_profile(
            all_rules,
            temp_dir=temp,
            python_executable=sys.executable,
            python_paths=tuple(path for path in sys.path if path),
            sse_port=self.port,
        )
        profile_path = temp / "seatbelt.sb"
        profile_path.write_text(profile, encoding="utf-8")
        profile_path.chmod(0o600)
        return [_SANDBOX_EXEC, "-f", str(profile_path), *command], {**extra_envs, "TMPDIR": str(temp)}
