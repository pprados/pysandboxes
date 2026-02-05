import inspect
import logging
import os
import re
import types
from importlib import resources
from pathlib import Path
from typing import Optional, List, Dict, NamedTuple, Set

from . import guard_files, guard_envs, guard_provider, guard_socket, guard_import
from .base_daemon import BaseDaemon
from .exception import SandBoxError
from .guard_envs import EnvsRules
from .guard_files import FileRules
from .guard_import import ImportRules, conv_patch_rules
from .guard_socket import SocketRules
from .learning import activate_learning
from .main_logger import format_ruleref, ErrorMsg, \
    pysandboxes_logger
from .remote.parameters import CONFIG_NAME
from .tools import remove_config_comments, substitute_config_env_vars, find_config
from .types import ConfigLines, Envs, ConfigLine

logger = logging.getLogger(__name__)


class ConfigSyntaxError(SandBoxError):
    def __init__(self, message: str, errors: List[str]):
        super().__init__()
        self.message = message
        self.errors = errors

    def __str__(self):
        return (self.message + "\n" +
                "\n".join(self.errors))


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


class AllRules(NamedTuple):
    config: ConfigLines
    envs: Envs
    os_sandbox: str
    use_py_sandbox: bool
    learning_path: Optional[Path]
    envs_rules: EnvsRules
    socket_rules: SocketRules
    file_rules: FileRules
    import_rules: ImportRules


def _read_config(config_path: Path) -> ConfigLines:
    return remove_config_comments([ConfigLine(line, config_path, ln + 1) for ln, line in
                                   enumerate(config_path.read_text().splitlines())])


def read_and_parse_config(
        config_path: Optional[Path],
        *,
        envs: Optional[Dict[str, str]] = None,
        extra_rules: Optional[List[str]] = None,
        exit_on_error: bool = False,
) -> AllRules:
    """
    Reads and parses the configuration file for the sandbox.

    The function follows this logic to find and process the configuration:
    - If `config_path` is not provided, it defaults to "./.py-sandboxes".
    - If the configuration file does not exist at the specified or default path,
      the sandbox enters learning mode. At the end of the execution, it will
      create a new configuration file at "./.py-sandboxes" based on the
      activities observed.
    - If `config_path` points to an existing file, that file is used for
      configuration.
    - If the configuration file contains a `--learning` directive pointing to
      itself, any new rules generated during the run are appended to the end of
      the file. The original file is backed up with a `.old` suffix before
      being modified.

    Args:
        config_path: The path to the configuration file.
        envs: A dictionary of environment variables to use for substitution.
              Defaults to `os.environ`.
        extra_rules: A list of additional rule strings to parse.
        exit_on_error: If True, the program will exit if a parsing error occurs.

    Returns:
        An `AllRules` object containing the parsed configuration.
    """
    if envs is None:
        envs = os.environ
    extra_lines = remove_config_comments(
        [ConfigLine(line, Path(), 0) for line in extra_rules]) if extra_rules else []

    if not config_path:
        config_path = Path(CONFIG_NAME)

    find_config_path = find_config(str(config_path))
    if not find_config_path:
        # Activate the learning mode
        # Load the template, and add learning mode
        with resources.as_file(
                resources.files(
                    __name__.rsplit('.', maxsplit=1)[:-1][
                        0] + '.templates') / 'py-sandbox.template'
        ) as resource_path:
            config = (
                    [ConfigLine(f"learning={CONFIG_NAME}", Path(), 0)] +
                    extra_lines +
                    _read_config(resource_path)
            )
    else:
        if not find_config_path and Path(CONFIG_NAME).exists():
            config_path = Path(CONFIG_NAME)
        else:
            config_path = Path(find_config_path)
        config = extra_lines + _read_config(config_path)
    return parse_config(config,
                        envs=envs,
                        exit_on_error=exit_on_error)


def parse_include(
        rules: ConfigLines,
) -> ConfigLines:
    includes = set()
    return _parse_include(includes, rules)


def _parse_include(
        includes: Set[Path],
        rules: ConfigLines,
) -> ConfigLines:
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
        *,
        envs: Optional[Dict[str, str]] = None,
        exit_on_error: bool = False,
) -> AllRules:
    if envs is None:
        envs = os.environ
    ienvs = Envs(envs)
    errors: List[ErrorMsg] = []  # Aggregate all errors

    # 1. Parse includes
    config = parse_include(config)

    # 2. Parse the rules, step by step
    envs_rules, sandbox_env, others = guard_envs.parse_rules(config, ienvs, errors)
    others = substitute_config_env_vars(others, ienvs)  # with main envs

    # 3. Parse others rules
    os_sandbox, use_pysandbox, learning_path, others = guard_provider.parse_rules(
        others, errors)
    socket_rules, others = guard_socket.parse_rules(others, errors)
    files_rules, others = guard_files.parse_rules(others, errors)
    import_rules, others = guard_import.parse_rules(others, errors)

    # 2. If some line are ignored, log a warning
    if others:
        for invalide_rule in others:
            pysandboxes_logger.warning(
                f"%s: Ignore invalid rule '%s'.",
                format_ruleref(invalide_rule),
                invalide_rule.rule
            )
    # 3. Print error
    if errors:
        errors = sorted(errors, key=lambda r: (str(r[1]), r[2]))
        if exit_on_error:
            os._exit(1)
        raise ConfigSyntaxError(
            f"Syntax error in config files.",
            [error[0] for error in errors])

    return AllRules(config,
                    sandbox_env,
                    os_sandbox,
                    use_pysandbox,
                    learning_path,
                    envs_rules,
                    socket_rules,
                    files_rules,
                    import_rules,
                    )


def get_config_path(config_path: Optional[Path]) -> Optional[Path]:
    # FIXME: merge files parameters?
    if not config_path:
        known_paths = [
            Path(".py-sandboxes"),  # Current directory
        ]
        body_from_users_or_os = []
        for path in known_paths:
            if path.exists():
                config_path = path
                break
    return Path(config_path) if isinstance(config_path, str) else config_path


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
    guard_import.activate_guard_import(
        conv_patch_rules(
            {
                **file_patch_rules,
                **socket_patch_rules,
                **env_patch_rules
            }
        ),
        all_rules.import_rules,
    )
    guard_envs.activate_guard(all_rules.envs_rules)
    guard_socket.activate_guard(all_rules.socket_rules)
    guard_files.activate_guard(all_rules.file_rules)
    if all_rules.learning_path:
        activate_learning(all_rules.learning_path)
