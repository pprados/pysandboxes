import inspect
import logging
import os
import types
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from . import guard_files, guard_env, guard_provider, guard_socket
from .guard_files import FilesRule
from .guard_socket import SocketRule
from .main_logger import format_ruleref, format_error_list, ErrorMsg
from .tools import remove_comments, substitute_env_vars
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


AllRules = Tuple[
    ConfigLines,  # Merged config
    Envs,  # sandbox env
    str,  # os_sandboxg
    List[SocketRule],  # Socket rules
    List[FilesRule],  # file rules
]


def _read_config(config_path: Path) -> ConfigLines:
    return remove_comments([ConfigLine(line, config_path, ln + 1) for ln, line in
                            enumerate(config_path.read_text().splitlines())])


def read_and_parse_config(
        config_path: Optional[Path],
        *,
        envs: Envs = os.environ,
        extra_rules: Optional[List[str]] = None,
        exit_on_error:bool = False,
) -> AllRules:
    if extra_rules is None:
        extra_lines = []
    else:
        extra_lines = remove_comments(
            [ConfigLine(line, "<extra>", 0) for line in extra_rules])

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
        envs: Envs = os.environ,
        exit_on_error:bool = False,
) -> AllRules:
    errors: List[ErrorMsg] = []  # Aggregate all errors

    # 1. Parse the rules, step by step
    sandbox_env, others = guard_env.parse_guard_envs(config, envs, errors)
    others = substitute_env_vars(others, envs)  # with main envs

    provider, others = guard_provider.parse_rules(others, errors)
    socket_rules, others = guard_socket.parse_rules(others, errors)
    files_rules, others = guard_files.parse_rules(others, errors)

    # 2. If some line are ignored, log a warning
    if others:
        for invalide_rule in others:
            logger.warning(
                f"%s: Ignore invalid rule '%s'.",
                format_ruleref(invalide_rule),
                invalide_rule.rule
            )
    # 3. Print error
    if errors:
        errors=sorted(errors, key=lambda r: (str(r[1]),r[2]))
        all_errors = "\n" + "\n".join([error[0] for error in errors])
        logger.error(all_errors)
        all_files_in_errors = list(set([repr(str(error[1])) for error in errors
                                        if error[1] != Path("")]))
        if exit_on_error:
            os._exit(1)
        raise ValueError(f"Syntax error in {format_error_list(all_files_in_errors)} ")

    return config, sandbox_env, provider, socket_rules, files_rules


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
        envs: Dict[str, str] = os.environ,
        args_rules: Optional[List[str]] = None,
        *,
        config: ConfigLines = None,
        outer_sandbox: str = None,
) -> None:
    if outer_sandbox:
        from pysandboxes.os_sandboxes import providers
        if outer_sandbox not in providers:
            raise ValueError(f"Unknown os-sandbox name: {outer_sandbox}")
        provider = providers[outer_sandbox]
        config, sandbox_env, os_sandbox, socket_rules, files_rules = provider.update_rules(
            envs=envs,
            config=config,
        )
    else:
        config, sandbox_env, os_sandbox, socket_rules, files_rules = (
            read_and_parse_config(envs=envs,
                                  config=config,
                                  extra_rules=args_rules))

    # Apply the rules
    # sys.stdin.shutdown()  # FIXME
    os.environ = sandbox_env
    guard_socket.activate_guard_socket(socket_rules)
    guard_files.activate_guard_files(files_rules)
