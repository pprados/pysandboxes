import inspect
import logging
import os
import types
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from . import guard_files, guard_env
from . import guard_socket
from .guard_files import Files_Rules
from .guard_socket import SocketRule
from .tools import remove_comments, substitute_env_vars
from .types import ConfigLines, Envs

logger = logging.getLogger(__name__)


def _get_caller_module(skip: int = 4) -> Optional[types.ModuleType]:
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
    List[Files_Rules],  # file rules
]


def read_and_parse_config(
        *,
        envs: Dict[str, str] = os.environ,
        config: ConfigLines,
        args_rules: Optional[List[str]] = None
) -> AllRules:
    # 1. try to find .pysandboxes in the caller module
    if args_rules is None:
        args_rules = []
    body_from_ressource = []
    # FIXME: a bug in importlib.resources.files
    # caller_module = _get_caller_module()
    # if caller_module:
    #     from importlib.metadata import files
    #     resource = files(caller_module.__name__).joinpath(".pysandboxes")
    #     resource = files(caller_module.__package__).joinpath(".pysandboxes")
    #     FIXME
    #     if resource.exists():
    #         with as_file(resource) as path:
    #             body_from_ressource = _read_config(path)
    #     pass


    body_from_users_or_os = remove_comments(config)
    # 3. Merge all files
    config = body_from_ressource + args_rules + body_from_users_or_os

    # 4. Parse the rules, step by step
    sandbox_env, others = guard_env.parse_guard_envs(config, envs)  # TODO: a virer lors outer !
    others = substitute_env_vars(others, envs)
    from pysandboxes import guard_provider
    provider, others = guard_provider.parse_rules(others)
    socket_rules, others = guard_socket.parse_rules(others)
    files_rules, others = guard_files.parse_rules(others)

    # 5. If some line are ignored, log a warning
    if others:
        for invalide_rule in others:
            logger.warning(f"Ignore invalid rule: {invalide_rule}")
    return config, sandbox_env, provider, socket_rules, files_rules


def get_config_path(config_path:Optional[Path]) -> Optional[Path]:
    # TODO: merge parameter with others ?
    if not config_path:
        known_paths = [
            Path(".py-sandbox"),  # Current directory
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
        config:ConfigLines = None,
        outer_sandbox: str = None,
) -> None:
    if outer_sandbox:
        from .remote.os_sandboxes import providers
        if outer_sandbox not in providers:
            raise ValueError(f"Unknown os-sandbox name: {outer_sandbox}")
        provider = providers[outer_sandbox]
        config, sandbox_env, os_sandbox, socket_rules, files_rules = provider.update_rules(
            envs=envs,
            config=config,
        )
    else:
        config,sandbox_env, os_sandbox, socket_rules, files_rules = (
            read_and_parse_config(envs=envs,
                                  config=config,
                                  args_rules=args_rules))

    # Apply the rules
    # sys.stdin.shutdown()  # FIXME
    os.environ = sandbox_env
    guard_socket.activate_guard_socket(socket_rules)
    guard_files.activate_guard_files(files_rules)
