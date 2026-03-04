# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Python-level sandbox implementation.

This module provides the core Python-level sandboxing functionality, including
configuration parsing, rule activation, and integration with various security
guards (files, network, imports, environment).
"""

import inspect
import logging
import os
import re
import sys
import types
from importlib import resources
from pathlib import Path
from typing import Any, cast

from . import (
    guard_envs,
    guard_files,
    guard_import,
    guard_provider,
    guard_self,
    guard_socket,
)
from .all_rules import AllRules
from .base_daemon import BaseDaemon
from .config import CONFIG_NAME
from .e import ConfigSyntaxError
from .learning import set_learning_path, set_learning_mode
from .main_logger import ErrorMsg, format_ruleref
from .sb_types import ConfigLine, ConfigLines, Envs
from .tools import Environ, remove_config_comments, substitute_config_env_vars

logger = logging.getLogger(__name__)


def _search_module_config(config_path: Path | None) -> Path:
    if not config_path:
        config_path = Path(CONFIG_NAME)
    # Try to find config filename
    pysb_module_name = __name__.split(".", 1)[0]
    # Search the module of the caller
    frame = sys._getframe()
    while cast(str, frame.f_globals.get("__name__", "__main__")).startswith(
            pysb_module_name + "."
    ):
        assert frame.f_back is not None
        frame = frame.f_back
    # Module of the caller
    from importlib.resources import files

    caller_module = frame.f_globals.get("__name__", "__main__").split(".", 1)[0]
    resource_config: Path | None = None
    if caller_module != "__main__":
        resource_path = cast(Path, files(caller_module))
        resource_config = resource_path / config_path
    if resource_config and resource_config.exists():
        config_path = resource_config
        logger.info("Use the resource %s from the caller module", config_path)
    else:
        # Else search in the current working directory
        config_path = Path.cwd() / config_path
    return config_path


def _get_caller_module(skip: int) -> types.ModuleType | None:
    """Returns the module of the caller.

    Args:
        skip: How many stack frames to skip.
            - skip=0: current function (_get_caller_module)
            - skip=1: function calling _get_caller_module
            - skip=2: caller of that function (default)

    Returns:
        The module object of the caller, or None if not found.
    """
    frame = inspect.currentframe()
    for _ in range(skip):
        if frame is not None:
            frame = frame.f_back
    if frame is not None:
        module = inspect.getmodule(frame)
        return module
    return None


def _read_config_and_remove_comments(config_path: Path) -> ConfigLines:
    return remove_config_comments(
        [
            ConfigLine(line, config_path, ln + 1)
            for ln, line in enumerate(config_path.read_text().splitlines())
        ]
    )


def load_and_parse_config(
        config_path: Path | None = None,
        *,
        envs: Environ | None = None,
        **extra_rules: dict[str, Any],
) -> AllRules:
    """Reads and parses the configuration file for the sandbox.

    This function implements a sophisticated configuration loading strategy:

    1. If no pysandboxes_config is provided, defaults to "./.py-sandboxes"
    2. If the config file doesn't exist, automatically enables learning mode
    3. In learning mode, creates a new config file based on observed behavior
    4. If config contains a --learn directive, appends new rules to existing file
    5. Original files are backed up with .old suffix before modification

    Args:
        config_path: Path to the configuration file. Defaults to "./.py-sandboxes".
        envs: Environment variables for substitution. Defaults to os.environ.
        **extra_rules: Additional rule strings to parse. Values can be strings
            or iterables of strings for the same key.

    Returns:
        An AllRules object containing the parsed configuration.

    Raises:
        ConfigSyntaxError: If configuration file has syntax errors.
    """
    if envs is None:
        envs = os.environ
    # Extra rules can be in form k=v or k=[v1,v2,...]
    extra_lines = []
    for k, all_v in extra_rules.items():
        k = k.replace("_", "-")
        if isinstance(all_v, set):
            extra_lines.extend([ConfigLine(f"{k}={v}", Path(), 0) for v in all_v])
        else:
            extra_lines.append(ConfigLine(f"{k}={all_v}", Path(), 0))

    if not config_path:
        config_path = Path(CONFIG_NAME)

    pysb_module_name = __name__.split(".", 1)[0]

    if "/" not in str(config_path):
        config_path = _search_module_config(config_path)

    if not config_path.exists():
        # Activate the learn mode
        # Load the template, and add learn mode
        with resources.as_file(
                resources.files(pysb_module_name + ".templates") / "py-sandbox.template"
        ) as resource_path:
            config = extra_lines + _read_config_and_remove_comments(resource_path)
    else:
        config = extra_lines + _read_config_and_remove_comments(config_path)
    return parse_config(
        config,
        config_path=config_path,
        envs=envs,
    )


def _parse_include(
        root_path: Path,
        includes: set[Path],
        rules: ConfigLines,
) -> ConfigLines:
    # includes parameter is to detect the recursive includes
    others: ConfigLines = []
    pattern = re.compile(r'^include\s+"(.+)"\s*$')
    for rule in rules:
        match = pattern.match(rule.rule)
        if match:
            filename = Path(match[1])
            if "/" not in str(filename):
                filename = root_path / filename
            filename = filename.expanduser().absolute()
            if filename not in includes:  # No loop of include
                try:
                    if filename.exists():
                        # Read the file
                        include_config = remove_config_comments(
                            [
                                ConfigLine(line, filename, ln + 1)
                                for ln, line in enumerate(
                                filename.read_text().split("\n")
                            )
                            ]
                        )
                        # Recursive include
                        includes.add(filename.absolute())
                        others.extend(
                            _parse_include(root_path, includes, include_config)
                        )
                except PermissionError:
                    pass  # Ignore
        else:
            others.append(rule)
    return others


def parse_provider_rules(
        rules: ConfigLines,
) -> tuple[ConfigLines, ConfigLines]:
    providers_rules = []
    ignore_rules = []

    for rule in rules:
        if "=" in rule.rule:
            if "." in rule.rule.split("=")[0]:
                providers_rules.append(rule)
            else:
                ignore_rules.append(rule)
        else:
            ignore_rules.append(rule)
    return providers_rules, ignore_rules


def parse_config(
        config: ConfigLines,
        config_path: Path,
        *,
        envs: Environ | None = None,
) -> AllRules:
    if envs is None:
        envs = os.environ
    errors: list[ErrorMsg] = []  # Aggregate all errors

    # 1. Parse includes
    config = _parse_include(config_path.parent, {config_path}, config)

    # 2. Parse the rules, step by step
    envs_rules, sandbox_env, others = guard_envs.parse_rules(config, envs, errors)
    others = substitute_config_env_vars(others, envs)  # with main envs

    # 3. Parse others rules
    (
        port,
        os_sandbox,
        use_py_sandbox,
        learning_path,
        learn,
        others,
    ) = guard_provider.parse_rules(config_path, others, errors)

    from pysandboxes.os_sandbox import providers_factory

    providers_rules, others = parse_provider_rules(others)
    os_sandbox_params, _ = providers_factory[os_sandbox](token="").parse_rules(providers_rules, errors)

    socket_rules, others, pin_dns = guard_socket.parse_rules(others, errors)
    files_rules, others = guard_files.parse_rules(others, errors)
    import_rules, others = guard_import.parse_rules(others, errors)

    # 2. If some line are ignored
    if others:
        for invalide_rule in others:
            errors.append(
                (
                    f"{format_ruleref(invalide_rule)}: "
                    f"Invalid rule {invalide_rule.rule!r}",
                    invalide_rule.path,
                    invalide_rule.ln,
                )
            )

    # 3. Print error
    if errors:
        errors = sorted(errors, key=lambda r: (str(r[1]), r[2]))
        raise ConfigSyntaxError(
            "Syntax error in config files.", [error[0] for error in errors]
        )

    if learn:
        # Force os_sandbox to subprocess
        os_sandbox = "subprocess"

    return AllRules(
        root_path=config_path,
        config=config,
        envs=sandbox_env,
        os_sandbox=os_sandbox,
        os_sandbox_params=os_sandbox_params,
        use_py_sandbox=use_py_sandbox,
        port=port,
        learning_path=learning_path,
        learn=learn,
        envs_rules=envs_rules,
        socket_rules=socket_rules,
        pin_dns=pin_dns,
        file_rules=files_rules,
        import_rules=import_rules,
    )


def activate_sandboxes(
        all_rules: AllRules,
        envs: Environ | None = None,
) -> None:
    if envs is None:
        envs = os.environ
    os_sandbox = all_rules.os_sandbox
    if os_sandbox:
        from pysandboxes.os_sandbox import providers_factory

        if os_sandbox not in providers_factory:
            raise ValueError(f"Unknown os-sandbox name: {os_sandbox}")
        os_provider: BaseDaemon = providers_factory[os_sandbox](token=None)
        # Offer the opportunity to update the rules (add, remove, etc)
        all_rules = os_provider.update_rules(
            all_rules=all_rules,
            envs=Envs(envs),
        )

    # Apply the rules
    env_patch_rules = guard_envs.patch_rules(all_rules.learn)
    file_patch_rules = guard_files.patch_rules(all_rules.learn)
    socket_patch_rules = guard_socket.patch_rules(all_rules.learn)
    import_patch_rules = guard_import.patch_rules(all_rules.learn)
    self_patch_rules = guard_self.patch_rules(all_rules.learn)
    guard_import.activate_guard_import(
        {
            **file_patch_rules,
            **socket_patch_rules,
            **env_patch_rules,
            **import_patch_rules,
            **self_patch_rules,
        },
        all_rules.import_rules,
    )

    guard_envs.activate_guard(all_rules.envs_rules)
    guard_socket.activate_guard(all_rules.socket_rules)
    guard_files.activate_guard(all_rules.file_rules)
    set_learning_mode(all_rules.learn)
    set_learning_path(all_rules.learning_path)
    guard_self.activate_guard()
