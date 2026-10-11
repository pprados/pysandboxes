# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Windows AppContainer subprocess provider."""

import json
import logging
import os
import sys
import uuid
from pathlib import Path

from ..all_rules import AllRules
from ..sb_types import Args, Envs
from ..tools import Environ
from .appcontainer_acl import (
    build_acl_plan,
    has_ignore_in_writable_exposure,
    has_loopback_network_rule,
    has_user_network_rules,
    network_capabilities,
)
from .client_subprocess_sse_daemon import BaseSubProcessDaemon, _child_env

logger = logging.getLogger(__name__)


class AppContainerSSEDaemon(BaseSubProcessDaemon):
    """Launch the SSE service in a per-run Windows AppContainer."""

    def _on_process_launched(self, pid: int) -> None:
        """Keep the trusted trampoline in a kill-on-close job owned by this daemon."""
        if sys.platform != "win32":
            return
        from .win_job import assign, close, create_kill_on_close_job

        job = create_kill_on_close_job()
        try:
            assign(job, pid)
        except BaseException:
            close(job)
            raise
        self._job_handle = job

    @classmethod
    def unavailable_reason(cls) -> str | None:
        """Report when Windows lacks the AppContainer profile API."""
        if sys.platform != "win32":
            return "AppContainer is available only on win32"
        try:
            userenv = __import__("ctypes").__dict__["WinDLL"]("userenv")
            _ = userenv.CreateAppContainerProfile
        except (AttributeError, OSError):
            return "Windows userenv.CreateAppContainerProfile is unavailable (Windows 8 or later is required)"
        return None

    def subprocess_cmd(
        self,
        all_rules: AllRules,
        envs: Environ,
        pipe_path: Path,
        temp: Path,
    ) -> tuple[Args, Environ]:
        """Write the trusted run plan and start the out-of-container trampoline."""
        child_command, _ = super().subprocess_cmd(all_rules, envs, pipe_path, temp)
        plan_path = temp / "appcontainer-plan.json"
        shared_socket_path = temp / "appcontainer-socket.bin"
        child_env = {**envs, **all_rules.envs} if all_rules.learn else dict(all_rules.envs)
        child_process_env = _child_env(Envs(child_env))
        if "LOCALAPPDATA" in os.environ:
            child_process_env.setdefault("LOCALAPPDATA", os.environ["LOCALAPPDATA"])
        plan = {
            "profile_name": f"pysb.{uuid.uuid4().hex}",
            "child_command": child_command,
            "env": child_process_env,
            "shared_socket_path": str(shared_socket_path),
            "port": self.port,
            "capabilities": network_capabilities(all_rules.socket_rules, self.port),
            "grants": [
                {"path": str(grant.path), "rights": grant.rights, "sid_kind": grant.sid_kind}
                for grant in build_acl_plan(all_rules, temp)
            ],
        }
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        trampoline_env = {
            key: os.environ[key]
            for key in ("LOCALAPPDATA", "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE")
            if key in os.environ
        }
        if not all_rules.use_py_sandbox and has_user_network_rules(all_rules.socket_rules, self.port):
            logger.warning(
                "AppContainer grants network classes only; host, port, protocol, and loopback rules "
                "are not OS-enforced when py-sandbox=false"
            )
        if has_loopback_network_rule(all_rules.socket_rules, self.port):
            logger.warning("AppContainer blocks loopback networking even when a net= rule allows it")
        if has_ignore_in_writable_exposure(all_rules.file_rules):
            logger.warning(
                "AppContainer ignore= masks existing paths only; new files under expose-rw= may be accessible"
            )
        return [sys.executable, "-m", "pysandboxes.remote.appcontainer_launcher", str(plan_path)], trampoline_env
