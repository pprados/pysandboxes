# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Rules aggregation module for PySandboxes.

This module provides data structures to collect and organize all security rules
from different guards (environment, files, network, imports) into a unified
configuration object.
"""

from pathlib import Path
from typing import Any, NamedTuple

from pysandboxes.guard_api import ApiRules
from pysandboxes.guard_envs import EnvsRules
from pysandboxes.guard_files import FilesRules
from pysandboxes.guard_import import ImportRules
from pysandboxes.guard_socket import PinDNS, SocketRules
from pysandboxes.immutable_dict import ImmutableDict
from pysandboxes.sb_types import ConfigLines, Envs


class AllRules(NamedTuple):
    """Aggregates all security rules and configuration settings.

    This data structure consolidates rules from all security guards along with
    general sandbox configuration into a single object for easy distribution
    throughout the system.

    Attributes:
        root_path: Directory the configuration was read from. Relative paths
            in the rules, and the files pulled in by an include, resolve
            against it.
        config: Raw configuration lines from config file.
        envs: Environment variables available in sandbox.
        os_sandbox: OS-level sandbox provider name.
        os_sandbox_params: Provider-specific settings, as parsed by the
            provider named by ``os_sandbox``.
        use_py_sandbox: Whether Python-level sandboxing is enabled.
        port: Local port the sandbox is reached on. ``-1`` asks for a free
            port to be picked at startup.
        learning_path: Path where learning mode rules are saved.
        learn: Whether learning mode is active.
        envs_rules: Environment variable access rules.
        socket_rules: Network access rules.
        pin_dns: Host names resolved once and pinned to their addresses, so a
            later lookup cannot redirect an allowed name elsewhere.
        file_rules: File system access rules.
        import_rules: Python import rules.
        api_rules: Sensitive API call rules.
    """

    root_path: Path
    config: ConfigLines
    envs: Envs
    os_sandbox: str
    os_sandbox_params: ImmutableDict[str, Any]
    use_py_sandbox: bool
    port: int
    learning_path: Path
    learn: bool
    envs_rules: EnvsRules
    socket_rules: SocketRules
    pin_dns: PinDNS
    file_rules: FilesRules
    import_rules: ImportRules
    api_rules: ApiRules = ()


EmptyRules = AllRules(
    root_path=Path(),
    config=[],
    envs=Envs({}),
    os_sandbox="subprocess",
    os_sandbox_params=ImmutableDict({}),
    use_py_sandbox=False,
    port=-1,
    learning_path=Path(),
    learn=False,
    envs_rules=(),
    socket_rules=(),
    pin_dns=ImmutableDict({}),
    file_rules=(),
    import_rules=(),
    api_rules=(),
)
