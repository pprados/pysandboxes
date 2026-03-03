# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Rules aggregation module for PySandboxes.

This module provides data structures to collect and organize all security rules
from different guards (environment, files, network, imports) into a unified
configuration object.
"""

from pathlib import Path
from typing import NamedTuple

from pysandboxes.config import CONFIG_NAME
from pysandboxes.guard_envs import EnvsRules
from pysandboxes.guard_files import FileRules
from pysandboxes.guard_import import ImportRules
from pysandboxes.guard_socket import SocketRules
from pysandboxes.sb_types import ConfigLines, Envs


class AllRules(NamedTuple):
    """Aggregates all security rules and configuration settings.

    This data structure consolidates rules from all security guards along with
    general sandbox configuration into a single object for easy distribution
    throughout the system.

    Attributes:
        config: Raw configuration lines from config file.
        envs: Environment variables available in sandbox.
        os_sandbox: OS-level sandbox provider name.
        use_py_sandbox: Whether Python-level sandboxing is enabled.
        learning_path: Path where learning mode rules are saved.
        learn: Whether learning mode is active.
        envs_rules: Environment variable access rules.
        socket_rules: Network access rules.
        file_rules: File system access rules.
        import_rules: Python import rules.
    """

    root_path: Path
    config: ConfigLines
    envs: Envs
    os_sandbox: str
    use_py_sandbox: bool
    learning_path: Path
    learn: bool
    envs_rules: EnvsRules
    socket_rules: SocketRules
    file_rules: FileRules
    import_rules: ImportRules


EmptyRules = AllRules(
    root_path=Path(),
    config=[],
    envs=Envs({}),
    os_sandbox="subprocess",
    use_py_sandbox=False,
    learning_path=Path(),
    learn=False,
    envs_rules=(),
    socket_rules=(),
    file_rules=(),
    import_rules=(),
)
