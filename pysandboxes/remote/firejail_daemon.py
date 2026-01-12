import logging
import sys
from pprint import pprint
from typing import List

from pysandboxes.guard_files import BindRule
from pysandboxes.guard_sandbox import read_and_parse_config
from pysandboxes.remote.subprocess_daemon import SubProcessDaemon, BaseSubProcessDaemon
from pysandboxes.remote.tools import which_command, get_venv

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
    def _subprocess(self) -> List[str]:
        from . import daemon

        need_root=False
        sandbox_env, provider, socket_rules, files_rules = read_and_parse_config()

        # assert provider == "firejail"
        args=[str(which_command("firejail"))]

        for env,val in sandbox_env.items():
            args.append(f"--env={env}={val}")

            # Add python site-packages to the whitelist
        major,minor,*_ = sys.version_info
        # args.append(f"--whitelist={get_venv()}/lib/python{major}.{minor}/site-packages")
        args.append(f"--whitelist={get_venv()}")
        # 	--whitelist=${VIRTUAL_ENV}/lib/python${PYTHON_VERSION}/site-packages \
        # 	--whitelist=${VIRTUAL_ENV}/include/* \

        for rule in files_rules:
            if isinstance(rule,BindRule):
                if rule.source == rule.dest:
                    args.append(f"--whitelist={rule.dest}")
                else:
                    args.append(f"--bind={rule.dest},{rule.source}")
                    need_root=True
                if not rule.write:
                    args.append(f"--read-only={rule.dest}")

        # TODO
        for rule in socket_rules:
            pass

        args.extend([
            "--env=PYTHONSTARTUP=",
            "--profile=python.profile",
            "--whitelist=/home/pprados/.pyenv",  # FIXME
            "--net=wlp113s0",  # FIXME
            "--netfilter=/etc/firejail/tcpserver.net",  # FIXME
            # "/bin/zsh"
            sys.executable,
            "-m",
            f"--outer-sandbox={provider}",
            daemon.__name__
        ])
        if need_root:
            logger.warning("Firejail needs root to run")
        pprint(args)
        print("----------")
        print(" \\\n".join(args))
        print("----------")
        return args

