import logging
import os
import shlex
import sys
from pathlib import Path
from typing import List, Tuple, Dict

from pysandboxes.guard_files import BindRule, IgnoreRule
from pysandboxes.guard_sandbox import read_and_parse_config
from pysandboxes.remote import daemon
from pysandboxes.remote.subprocess_daemon import BaseSubProcessDaemon
from pysandboxes.remote.tools import which_command, get_venv, get_default_gateway_info, \
    suggest_package_installation
from pysandboxes.tools import read_config, substitute_env_vars

logger = logging.getLogger(__name__)


#   "--env=PYTHONSTARTUP="
#   --rlimit-as=${RLIMIT} \
#   --rlimit-cpu=${TIME_OUT} \
#   --rlimit-fsize=${FSIZE} \
#   --rlimit-nproc=${NPROC} \
#   --rlimit-nofile=${NOFILE} \
#   --rlimit-sigpending=1 \
#   --machine-id \
#   --nice=${NICE} \
# 	--profile=python.profile \
# 	--hostname=python-sandbox \
# 	--whitelist=${PWD} \
# 	--whitelist=${VIRTUAL_ENV}/lib/python${PYTHON_VERSION}/site-packages \
# 	--whitelist=${VIRTUAL_ENV}/include/* \
# 	--bind=${VIRTUAL_ENV}/lib/python${PYTHON_VERSION}/site-packages,/usr/local/lib/python${PYTHON_VERSION}/site-packages \
class FireJailDaemon(BaseSubProcessDaemon):
    def _firejail_args(self, envs: Dict[str, str]) -> List[str]:

        if not which_command("firejail"):
            logger.error("firejail not found. Install it with:")
            logger.error(suggest_package_installation("firejail"))
            sys.exit(1)

        need_root = False
        from importlib.resources import files
        # Reads contents with UTF-8 encoding and returns str.
        sandbox_env, provider, socket_rules, files_rules = read_and_parse_config(
            envs=envs)

        # assert provider == "firejail"
        args = [str(which_command("firejail"))]

        # Add default parameters
        firejail_conf = read_config(
            Path(files(__name__).joinpath('firejail.profile')))
        firejail_conf = substitute_env_vars(firejail_conf, envs)

        for line in firejail_conf:
            args.extend(shlex.split(line))

        # Extend mapping if the python version use a link
        major, minor, release_level, *_ = sys.version_info
        prg = sys.executable
        while os.path.islink(prg):
            prg = os.readlink(prg)
            if ".pyenv" in prg:
                prg = prg[:(prg.find(".pyenv/") + len(".pyenv/"))]
            args.extend([
                f"--whitelist={os.path.dirname(prg)}",
                f"--read-only={os.path.dirname(prg)}",
            ])

        # Same place
        args.extend([
            f"--whitelist={get_venv()}",
            f"--read-only={get_venv()}",
        ])
        # FIXME Need root
        # args.append(f"--bind={get_venv()},/usr/local")

        # Add files rules
        for rule in files_rules:
            if isinstance(rule, BindRule):
                if rule.source == rule.dest:
                    args.append(f"--whitelist={rule.dest}")
                else:
                    args.append(f"--bind={rule.dest},{rule.source}")
                    need_root = True
                if not rule.write:
                    args.append(f"--read-only={rule.dest}")
            elif isinstance(rule, IgnoreRule):
                args.append(f"--blacklist={rule.source}")  # FIXME

        # TODO Add socket rules
        # --netfilter
        if socket_rules:
            gw = get_default_gateway_info()
            if gw:
                args.append(f"--defaultgw={gw[0]}")
                args.append(f"--net={gw[1]}")
            for rule in socket_rules:
                pass

        # TODO: Add tmp rules
        # --tmpfs DEST

        args.extend(["env", "-i"])
        for env, val in sandbox_env.items():
            args.append(f"{env}={val}")

        if need_root:
            logger.warning("Firejail needs root to run")
        return args

    def _subprocess(self) -> List[str]:
        args = self._firejail_args()
        args.extend([
            sys.executable, "-m", f"--outer-sandbox=firejail", daemon.__name__
        ])
        return args

    def bash_args(self, envs: Dict[str, str]) -> Tuple[List[str], Dict[str, str]]:
        args = self._firejail_args(envs)
        args.extend([
            "PS1=[os-sandbox-firejail] $ ",
            "/bin/bash", "--norc", "--noprofile", "-i",
        ])
        return args, {}
