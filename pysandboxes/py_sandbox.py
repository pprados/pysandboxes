import inspect
import logging
import os
import re
import sys
import types
from importlib import resources
from pathlib import Path
from typing import Optional, List, Dict, Set, cast

from . import guard_envs, guard_provider, guard_socket, guard_files, guard_import
from .all_rules import AllRules
from .base_daemon import BaseDaemon
from .config import CONFIG_NAME
from .e import ConfigSyntaxError
from .learning import activate_learning
from .main_logger import format_ruleref, ErrorMsg
from .sb_types import ConfigLines, Envs, ConfigLine
from .tools import remove_config_comments, substitute_config_env_vars

logger = logging.getLogger(__name__)


def _get_caller_module(skip: int) -> Optional[types.ModuleType]:
    """
    Returns the module of the caller.

    Parameters:
        skip (int): How many stack frames to skip.
                    skip=0 -> current function (_get_caller_module),
                    skip=1 -> function calling _get_caller_module,
                    skip=2 -> caller of that function (default).

    Returns:
        ModuleType | None: The module object of the caller, or None if not found.
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
    return remove_config_comments([ConfigLine(line, config_path, ln + 1) for ln, line in
                                   enumerate(config_path.read_text().splitlines())])


def load_and_parse_config(
        config_path: Optional[Path] = None,
        *,
        envs: Optional[Dict[str, str]] = None,
        **extra_rules,
) -> AllRules:
    """
    Reads and parses the configuration file for the sandbox.

    The function follows this logic to find and process the configuration:
    - If `config_path` is not provided, it defaults to "./.py-sandboxes".
    - If the configuration file does not exist at the specified or default path,
      the sandbox enters learn mode. At the end of the execution, it will
      create a new configuration file at "./.py-sandboxes" based on the
      activities observed.
    - If `config_path` points to an existing file, that file is used for
      configuration.
    - If the configuration file contains a `--learn` directive pointing to
      itself, any new rules generated during the run are appended to the end of
      the file. The original file is backed up with a `.old` suffix before
      being modified.

    Args:
        config_path: The path to the configuration file.
        envs: A dictionary of environment variables to use for substitution.
              Defaults to `os.environ`.
        extra_rules: A list of additional rule strings to parse. Mays be string
         or Iterable of strings for the same key
        exit_on_error: If True, the program will exit if a parsing error occurs.

    Returns:
        An `AllRules` object containing the parsed configuration.
    """
    if envs is None:
        envs = os.environ
    # Extra rules can be in form k=v or k=[v1,v2,...]
    extra_lines = []
    for k, all_v in extra_rules.items():
        k = k.replace('_', '-')  # TODO: params import
        if isinstance(all_v, Set):
            extra_lines.extend([ConfigLine(f"{k}={v}", Path(), 0) for v in all_v])
        else:
            extra_lines.append(ConfigLine(f"{k}={all_v}", Path(), 0))

    if not config_path:
        config_path = Path(CONFIG_NAME)

    if '/' not in str(config_path):
        # Try to find config filename
        pysb_module_name = __name__.split('.', 1)[0]

        # Search the module of the caller
        frame = sys._getframe()
        while cast(str, frame.f_globals.get("__name__", "__main__")).startswith(
                pysb_module_name + "."):
            assert frame.f_back is not None
            frame = frame.f_back

        # Module of the caller
        from importlib.resources import files
        caller_module = frame.f_globals.get("__name__", "__main__").split('.', 1)[0]
        resource_config = None
        if caller_module != "__main__":
            resource_path = files(caller_module)
            resource_config = resource_path / config_path
        if resource_config and resource_config.exists():
            config_path = resource_config
            logger.info("Use the resource %s from the caller module",
                         config_path)
        else:
            # Else search in the current working directory
            config_path = Path.cwd() / config_path

    if not config_path.exists():
        # Activate the learn mode
        # Load the template, and add learn mode
        with resources.as_file(
                resources.files(
                    pysb_module_name + '.templates') / 'py-sandbox.template'
        ) as resource_path:
            config = (
                    extra_lines +
                    _read_config_and_remove_comments(resource_path)
            )
    else:
        config = extra_lines + _read_config_and_remove_comments(config_path)
    return parse_config(config,
                        config_path=config_path,
                        envs=envs,
                        )


def _parse_include(
        includes: Set[Path],
        rules: ConfigLines,
) -> ConfigLines:
    # includes parameter is to detect the recursive includes
    others: ConfigLines = []
    pattern = re.compile(r'^include\s+"(.+)"\s*$')
    for rule in rules:
        match = pattern.match(rule.rule)
        if match:
            filename = Path(match[1]).expanduser().absolute()
            if filename not in includes:  # No loop of include
                try:
                    if filename.exists():
                        # Read the file
                        include_config = remove_config_comments(
                            [ConfigLine(line, filename, ln + 1) for ln, line in
                             enumerate(filename.read_text().split("\n"))])
                        # Recursive include
                        includes.add(filename.absolute())
                        others.extend(
                            _parse_include(includes, include_config))
                except PermissionError:
                    pass  # Ignore
        else:
            others.append(rule)
    return others


def parse_config(
        config: ConfigLines,
        config_path: Path,
        *,
        envs: Optional[Dict[str, str]] = None,
) -> AllRules:
    if envs is None:
        envs = os.environ
    ienvs = Envs(envs)
    errors: List[ErrorMsg] = []  # Aggregate all errors

    # 1. Parse includes
    config = _parse_include({config_path}, config)

    # 2. Parse the rules, step by step
    envs_rules, sandbox_env, others = guard_envs.parse_rules(config, ienvs, errors)
    others = substitute_config_env_vars(others, ienvs)  # with main envs

    # 3. Parse others rules
    os_sandbox, use_py_sandbox, learning_path, learn, others = guard_provider.parse_rules(
        others, errors)
    socket_rules, others = guard_socket.parse_rules(others, errors)
    files_rules, others = guard_files.parse_rules(others, errors)
    import_rules, others = guard_import.parse_rules(others, errors)

    # 2. If some line are ignored
    if others:
        for invalide_rule in others:
            errors.append((
                f"{format_ruleref(invalide_rule)}: "
                f"Invalid rule {invalide_rule.rule!r}",
                invalide_rule.path,
                invalide_rule.ln,
            ))

    # 3. Print error
    if errors:
        errors = sorted(errors, key=lambda r: (str(r[1]), r[2]))
        raise ConfigSyntaxError(
            f"Syntax error in config files.",
            [error[0] for error in errors])

    return AllRules(config=config,
                    envs=sandbox_env,
                    os_sandbox=os_sandbox,
                    use_py_sandbox=use_py_sandbox,
                    learning_path=learning_path,
                    learn=learn,
                    envs_rules=envs_rules,
                    socket_rules=socket_rules,
                    file_rules=files_rules,
                    import_rules=import_rules,
                    )


def activate_sandboxes(
        all_rules: AllRules,
        envs: Optional[Dict[str, str]] = None,
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
    env_patch_rules = guard_envs.patch_rules(all_rules.learning_path)
    file_patch_rules = guard_files.patch_rules()
    socket_patch_rules = guard_socket.patch_rules()
    import_patch_rules = guard_import.patch_rules()
    guard_import.activate_guard_import(
        {
            **file_patch_rules,
            **socket_patch_rules,
            **env_patch_rules,
            **import_patch_rules,
        },
        all_rules.import_rules,
    )
    guard_envs.activate_guard(all_rules.envs_rules)
    guard_socket.activate_guard(all_rules.socket_rules)
    guard_files.activate_guard(all_rules.file_rules)
    if all_rules.learn:
        activate_learning(all_rules.learning_path)
