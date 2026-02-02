import inspect
import logging
import os
import types
from pathlib import Path
from typing import Optional, List, Dict, NamedTuple

from . import guard_files, guard_env, guard_provider, guard_socket
from .base_daemon import BaseDaemon
from .guard_files import FileRules
from .guard_socket import SocketRules
from .main_logger import format_ruleref, format_error_list, ErrorMsg, pysandboxes_logger
from .tools import remove_config_comments, substitute_config_env_vars
from .types import ConfigLines, Envs, ConfigLine

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


class AllRules(NamedTuple):
    config: ConfigLines
    envs: Envs
    os_sandbox: str
    use_py_sandbox: bool
    socket_rules: SocketRules  # TODO: en faire un tuple pour le rendre immuable
    file_rules: FileRules


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
    if envs is None:
        envs = os.environ
    if extra_rules is None:
        extra_lines = []
    else:
        extra_lines = remove_config_comments(
            [ConfigLine(line, Path(), 0) for line in extra_rules])

    # 1. try to find .pysandboxes in the caller module
    body_from_ressource = []
    # caller_module = _get_caller_module(skip=3)
    # if caller_module:
    #     from importlib.metadata import files
    #     try:
    #         # FIXME: test
    #         resource = files(caller_module.__name__).joinpath(".pysandboxes")
    #         if resource.exists():
    #             from importlib.resources import as_file
    #             with as_file(resource) as path:
    #                 body_from_ressource = _read_config(path)
    #     except PackageNotFoundError:
    #         pass  # Ignore

    # 2. try to find .pysandboxes in the current directory
    if not config_path and Path(".py-sandboxes").exists():
        config_path = Path(".py-sandboxes")
    return parse_config(extra_lines + _read_config(config_path),
                        envs=envs,
                        exit_on_error=exit_on_error)


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

    # 1. Parse the socket_rules, step by step
    sandbox_env, others = guard_env.parse_guard_envs(config, ienvs, errors)
    others = substitute_config_env_vars(others, ienvs)  # with main envs

    os_sandbox, use_pysandbox, others = guard_provider.parse_rules(others, errors)
    socket_rules, others = guard_socket.parse_rules(others, errors)
    files_rules, others = guard_files.parse_rules(others, errors)

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
        all_errors = "\n" + "\n".join([error[0] for error in errors])
        logger.error(all_errors)
        all_files_in_errors = list(set([repr(str(error[1])) for error in errors
                                        if error[1] != Path("")]))
        if exit_on_error:
            os._exit(1)
        raise ValueError(f"Syntax error in {format_error_list(all_files_in_errors)} ")

    return AllRules(config, sandbox_env, os_sandbox, use_pysandbox, socket_rules,
                    files_rules)


def get_config_path(config_path: Optional[Path]) -> Optional[Path]:
    # TODO: merge parameter with others ?
    if not config_path:
        known_paths = [
            Path(".py-sandboxes"),  # Current directory
            Path("~/.config/pysandboxes/py-sandbox").expanduser(),
            Path("~/.local/share/pysandboxes/py-sandbox").expanduser(),
            Path("/etc/pysandboxes/py-sandbox"),
            Path("/usr/share/pysandboxes/py-sandbox"),
            Path("/var/lib/pysandboxes/py-sandbox"),
        ]
        body_from_users_or_os = []
        for path in known_paths:
            if path.exists():
                config_path = path
                break
    return Path(config_path) if isinstance(config_path, str) else config_path


def activate_sandboxes(  # FIXME: split en 2 pour éviter les paramètres parasites ?
        all_rules: AllRules,
        os_sandbox: str,
        envs: Optional[Dict[str, str]] = None,  # FIXME: dict or Env?
) -> None:
    if envs is None:
        envs = os.environ
    if os_sandbox:
        from pysandboxes.os_sandbox import providers_factory
        if os_sandbox not in providers_factory:
            raise ValueError(f"Unknown os-sandbox name: {os_sandbox}")
        os_provider: BaseDaemon = providers_factory[os_sandbox](token=None)
        all_rules = os_provider.update_rules(
            all_rules=all_rules,
            envs=Envs(envs),
        )

    # Apply the rules
    # sys.stdin.shutdown()  # FIXME: Compléter l'activation des règles
    os.environ = all_rules.envs
    guard_socket.activate_guard_socket(all_rules.socket_rules)
    guard_files.activate_guard_files(all_rules.file_rules)
