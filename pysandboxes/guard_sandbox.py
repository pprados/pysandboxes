import inspect
import logging
import os
import re
import sys
import types
from pathlib import Path
from typing import Optional, List, Dict, Tuple

from . import guard_files, guard_env
from . import guard_socket
from .guard_files import Files_Rules
from .guard_socket import SocketRule
from .tools import read_config, substitute_env_vars

logger = logging.getLogger(__name__)


def get_caller_module(skip: int = 2) -> Optional[types.ModuleType]:
    """
    Returns the module of the caller.

    Parameters:
        skip (int): How many stack frames to skip.
                    skip=0 -> current function (get_caller_module),
                    skip=1 -> function calling get_caller_module,
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


AllRules=Tuple[
    Dict[str,str],
    str,
    List[SocketRule],
    List[Files_Rules]
]

def read_and_parse_config(
        envs: Dict[str, str] = os.environ,
        args_rules:Optional[List[str]]=None
) -> AllRules:
    # 1. try to find .pysandboxes in the caller module
    if args_rules is None:
        args_rules = []
    body_from_ressource = []
    # FIXME: a bug in importlib.resources.files
    # caller_module = get_caller_module()
    # if caller_module:
    #     resource = files(caller_module.__name__).joinpath(".pysandboxes")
    #     # resource = files(caller_module.__package__).joinpath(".pysandboxes")
    #     if resource.exists():
    #         with as_file(resource) as path:
    #             body_from_ressource = _read_config(path)

    # 2. try to find .pysandboxes in special directories
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
            body_from_users_or_os = read_config(path)
            break
    # 3. Merge all files
    rules = body_from_ressource + args_rules + body_from_users_or_os

    # 4. Parse the rules, step by step
    sandbox_env, others =guard_env.parse_guard_envs(rules, envs)
    others = substitute_env_vars(others, envs)
    from pysandboxes import guard_provider
    provider, others = guard_provider.parse_rules(others)
    socket_rules, others = guard_socket.parse_rules(others)
    files_rules, others = guard_files.parse_rules(others)

    # 5. If some line are ignored, log a warning
    if others:
        for invalide_rule in others:
            logger.warning(f"Ignore invalid rule: {invalide_rule}")
    return sandbox_env, provider, socket_rules,files_rules


known_paths = [
    Path(".pysandboxes"),  # Current directory
    Path("~/.config/pysandboxes/pysandboxes").expanduser(),
    Path("~/.local/share/pysandboxes/pysandboxes").expanduser(),
    Path("/etc/pysandboxes/pysandboxes"),
    Path("/usr/share/pysandboxes/pysandboxes"),
    Path("/var/lib/pysandboxes/pysandboxes"),
]


def activate_sandboxes(
        envs: Dict[str, str] = os.environ,
        args_rules:Optional[List[str]]=None,
) -> None:

    sandbox_env,provider,socket_rules,files_rules = read_and_parse_config(envs,args_rules)

    # Apply the rules
    sys.stdin.close()
    os.environ=sandbox_env
    guard_socket.activate_guard_socket(socket_rules)
    guard_files.activate_guard_files(files_rules)


