# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What the rules of a profile become for Docker Sandboxes (``sbx``): network rules, mounts and masks."""

import fnmatch
import logging
import os
from collections.abc import Iterable
from ipaddress import IPv4Network, IPv6Network
from typing import NamedTuple

from ..all_rules import AllRules
from ..egress_filter import NameRule
from ..guard_files import FSExposeRule, IgnoreRule
from ..guard_socket import Action, Direction, Kind

logger = logging.getLogger(__name__)

_ALL_PORTS = range(65536)
_MAX_PORTS_PER_RULE = 64
# The image brings its own system: a host directory mounted over one would replace the guest's libraries.
_IMAGE_OWNED = ("/usr", "/etc", "/bin", "/sbin", "/lib", "/lib64", "/proc", "/dev", "/sys", "/run", "/boot")


class SbxRules(NamedTuple):
    """The ``sbx policy`` resources of a sandbox: ``allow`` and ``deny`` lists of ``host[:port]`` patterns."""

    allow: tuple[str, ...]
    deny: tuple[str, ...]


class Mounts(NamedTuple):
    """The host paths the guest receives: read-only and read-write directories."""

    ro: tuple[str, ...]
    rw: tuple[str, ...]


def _strip(path: str) -> str:
    return path.rstrip("/") or "/"


def is_inside(path: str, parents: Iterable[str]) -> bool:
    """Tell whether ``path`` is one of ``parents`` or below one of them."""
    return any(path == parent or path.startswith(parent.rstrip("/") + "/") for parent in parents)


def _host_interpreter_prefixes() -> set[str]:
    import sys

    return {os.path.realpath(sys.base_prefix)}


def is_image_owned(path: str) -> bool:
    """Tell whether ``path`` lies in a directory the guest image owns, where a host mount would break the guest."""
    return is_inside(path, _IMAGE_OWNED)


def _suffixes(ports: tuple[int, ...] | range) -> list[str] | None:
    """The ``:PORT`` suffixes of a rule, ``[""]`` for every port, ``None`` when the list is too long to emit."""
    if ports == _ALL_PORTS:
        return [""]
    listed = list(ports)
    if len(listed) > _MAX_PORTS_PER_RULE:
        return None
    return [f":{port}" for port in listed]


def _host_of(network: IPv4Network | IPv6Network, name_of: dict[str, str]) -> list[str]:
    """The ``sbx`` hosts a network stands for: every address, or all hosts for ``0.0.0.0/0``."""
    if network.prefixlen == 0:
        return ["**"]
    if network.num_addresses == 1:
        address = network.network_address.compressed
        hosts = [f"[{address}]" if network.version == 6 else address]
        return [*([name_of[address]] if address in name_of else []), *hosts]
    return [network.compressed]


def _pinned_names(all_rules: AllRules) -> dict[str, str]:
    """Return the name each pinned address came from, so a rule on an address also opens the name (SNI, ``Host``)."""
    names: dict[str, str] = {}
    for name, infos in all_rules.pin_dns.items():
        for info in infos:
            names.setdefault(str(info[4][0]), name)
    return names


def _name_resources(rule: NameRule) -> list[str]:
    pattern = rule.pattern.lower()
    if pattern.startswith("="):
        hosts = [pattern[1:]]
    elif pattern.startswith("*."):
        hosts = ["**." + pattern[2:]]
    else:
        hosts = [pattern, "**." + pattern]
    if "tcp" not in rule.kinds:
        return []
    if not rule.ports:
        return hosts
    return [f"{host}:{port}" for host in hosts for low, high in rule.ports for port in range(low, high + 1)]


def sbx_rules(all_rules: AllRules) -> SbxRules:
    """Translate the ``net=`` rules into ``sbx`` resources; what cannot be expressed is reported and left closed.

    ``sbx`` judges a connection by the name it asks for (SNI or ``Host``), or by the address when it names none: a
    rule on an address that has a pinned name is emitted for both. Incoming rules and DNS are not translated: DNS
    goes through the resolver of ``sbx``. UDP stays closed unless the settings of ``sbx`` enable it.
    """
    allow: list[str] = []
    deny: list[str] = []
    name_of = _pinned_names(all_rules)
    for rule in all_rules.socket_rules:
        if Direction.OUT not in rule.directions or Kind.TCP not in rule.mask.kinds:
            if Direction.OUT in rule.directions and rule.action == Action.ALLOW:
                logger.warning("docker-sandbox does not open UDP: %s stays closed", rule.mask.network)
            continue
        suffixes = _suffixes(rule.mask.ports)
        if suffixes is None:
            logger.warning(
                "docker-sandbox omits a rule of more than %d ports on %s", _MAX_PORTS_PER_RULE, rule.mask.network
            )
            continue
        if rule.mask.network.version == 6:
            logger.warning("docker-sandbox IPv6 rule on %s is not verified", rule.mask.network)
        target = allow if rule.action == Action.ALLOW else deny
        for host in _host_of(rule.mask.network, name_of):
            if host == "**" and suffixes == [""]:
                logger.warning("the profile allows every destination: docker-sandbox opens all hosts")
            target.extend(host + suffix for suffix in suffixes)
    for name_rule in all_rules.name_rules:
        (allow if name_rule.allow else deny).extend(_name_resources(name_rule))
    return SbxRules(tuple(dict.fromkeys(allow)), tuple(dict.fromkeys(deny)))


def guest_python_path(host_path: Iterable[str], exposed: Iterable[str], cwd: str) -> list[str]:
    """Return the entries of the ``sys.path`` of the host that the guest can import from, in the same order."""
    exposed = list(exposed)
    entries: list[str] = []
    for entry in host_path:
        path = os.path.abspath(entry or cwd)
        real = os.path.realpath(path)
        if not os.path.isdir(real) or is_inside(real, _host_interpreter_prefixes()):
            continue
        if (is_inside(path, exposed) or is_inside(real, exposed)) and path not in entries:
            entries.append(path)
    return entries


def mounts(all_rules: AllRules, *, extra_ro: Iterable[str] = ()) -> Mounts:
    """Return the host paths the guest receives; ``extra_ro`` is what the provider adds.

    A path exposed both ways ends up read-write. The directories the image owns, the host's interpreter and the paths
    that do not exist are left out; a file is mounted read-only.
    """
    write: dict[str, bool] = {}
    for rule in all_rules.file_rules:
        if not isinstance(rule, FSExposeRule):
            continue
        path = _strip(rule.path)
        if is_image_owned(path) or is_inside(os.path.realpath(path), _host_interpreter_prefixes()):
            continue
        if not os.path.exists(path):
            continue
        writable = rule.write
        if writable and not os.path.isdir(path):
            logger.warning("docker-sandbox shares only directories read-write: %s is exposed read-only", path)
            writable = False
        write[path] = write.get(path, False) or writable
    ro = [path for path, writable in write.items() if not writable]
    rw = [path for path, writable in write.items() if writable]
    ro.extend(path for path in extra_ro if path not in ro and path not in rw)
    return Mounts(tuple(ro), tuple(rw))


def mask_targets(all_rules: AllRules, cwd: str, exposed: list[str]) -> list[tuple[str, bool]]:
    """Return ``(path, is_directory)`` of what ``ignore=`` rules hide inside the exposed paths."""
    patterns = [rule.source for rule in all_rules.file_rules if isinstance(rule, IgnoreRule)]
    if not patterns:
        return []
    targets: dict[str, bool] = {}
    for tree in dict.fromkeys(os.path.realpath(root) for root in [cwd, *exposed] if os.path.isdir(root)):
        for directory, directories, files in os.walk(tree):
            for name in directories + files:
                if not any(fnmatch.fnmatch(name, pattern) for pattern in patterns):
                    continue
                path = os.path.join(directory, name)
                target = os.path.realpath(path) if os.path.islink(path) else path
                if os.path.exists(target) and is_inside(target, exposed):
                    targets[target] = os.path.isdir(target)
    return list(targets.items())
