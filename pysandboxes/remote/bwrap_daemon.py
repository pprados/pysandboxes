import logging
import os
import shlex
import sys
from pathlib import Path
from typing import List, Dict, Tuple

from . import daemon
from ..types import Envs, ConfigLines, Args
from .subprocess_daemon import SubProcessDaemon, BaseSubProcessDaemon
from .tools import which_command, get_venv, suggest_package_installation
from ..guard_files import BindRule
from ..py_sandbox import read_and_parse_config, AllRules
from ..tools import remove_comments, substitute_env_vars

logger = logging.getLogger(__name__)


class BWrapDaemon(BaseSubProcessDaemon):
    def update_rules(self,envs: Envs, config: ConfigLines) -> AllRules:
        raise NotImplementedError() # TODO

    def _bwrap_args(self,envs:Envs) -> Args:

        if not which_command("bwrap"):
            logger.error("bwrap not found.  Install it with:")
            logger.error(suggest_package_installation("bwrap"))
            sys.exit(1)

        from importlib.resources import files
        # Reads contents with UTF-8 encoding and returns str.
        config, sandbox_env, provider, socket_rules, files_rules = (
            read_and_parse_config(envs,config=config))

        # assert provider == "bwrap"
        args = [str(which_command("bwrap"))]

        # Add default parameters
        bwrap_conf = remove_comments(Path(files(__name__).joinpath('bwrap.profile')))
        bwrap_conf = substitute_env_vars(bwrap_conf, envs)
        for line in bwrap_conf:
            args.extend(shlex.split(line))

        # Add env variables
        for env, val in sandbox_env.items():
            args.extend(["--setenv", env, val])

        # Extend mapping if the python version use a link
        major, minor, release_level,*_ = sys.version_info
        prg = sys.executable
        while os.path.islink(prg):
            prg = os.readlink(prg)
            if ".pyenv" in prg:
                prg=prg[:(prg.find(".pyenv/")+len(".pyenv/"))]
            args.extend(["--ro-bind", os.path.dirname(prg), os.path.dirname(prg)])


        # Same place
        args.extend(["--ro-bind", get_venv(), get_venv()])
        args.extend(["--ro-bind", get_venv(), "/usr/local"])
        # args.extend(["--ro-bind",
        #              f"/usr/lib/python{major}.{minor}/encodings",
        #              f"/usr/lib/python{major}.{minor}/encodings"])

        # Add files rules
        for rule in files_rules:
            if isinstance(rule, BindRule):
                if rule.write:
                    args.extend(["--bind", rule.source, rule.dest])
                else:
                    args.extend(["--ro-bind", rule.source, rule.dest])

        # TODO Add socket rules
        for rule in socket_rules:
            pass

        # TODO: Add tmp rules
        # --tmpfs DEST

        return args

    def _subprocess(self) -> Args:
        args=self._bwrap_args()
        args.extend([
            sys.executable, "-m", f"--outer-sandbox=bwrap", daemon.__name__
        ])
        return args

    def bash_args(self,envs:Envs) -> Tuple[Args, Envs]:
        args=self._bwrap_args(envs)
        args.extend([
            "--setenv","PS1","[os-sandbox-bwrap] $ ",
            "--ro-bind","/bin","/bin",
            "--ro-bind","/lib","/lib",
            "--ro-bind","/lib64","/lib64",
            "/bin/bash", "--norc", "--noprofile", "-i",
        ])
        return args,{}

