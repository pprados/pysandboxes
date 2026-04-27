# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Abstract base for VM-based SSE daemons (e.g. QEMU).

VMSSEDaemon extends BaseSubProcessDaemon for providers whose "subprocess" is
a VM process (e.g. QEMU) rather than a Python process. Subclasses must
override _re_start_cmd to call launch_sandbox(args, pipe_path=..., ...) with
args only — do not append ["--_named-pipe", str(pipe_path)] to args; the guest
receives config by provider-specific means (e.g. HTTP from host).

Shared host-side behaviour for ``python-sb`` (temp prefix, guest run mount,
console filtering, guest exitcode file) lives here so ``python_sb`` stays
provider-agnostic.
"""

import asyncio
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, TextIO

from ..all_rules import AllRules
from .client_subprocess_sse_daemon import BaseSubProcessDaemon
from .qemu_guest_console_io import (
    PYTHON_OUTPUT_END,
    PYTHON_OUTPUT_START,
    qemu_wait_and_filter_console,
    read_qemu_guest_exitcode,
)

__all__ = [
    "VMSSEDaemon",
    "PYTHON_OUTPUT_END",
    "PYTHON_OUTPUT_START",
]


class VMSSEDaemon(BaseSubProcessDaemon, ABC):
    """Base class for VM-based sandbox daemons (e.g. QEMU).

    The "subprocess" is the VM process (e.g. qemu-system-x86_64). Configuration
    is passed to the guest by provider-specific means. Subclasses must override
    _re_start_cmd to pass the VM command line only to launch_sandbox (no
    --_named-pipe args appended).
    """

    __slots__ = ()

    #: Prefix for host ``tempfile.TemporaryDirectory`` (shared run dir).
    host_run_temp_prefix: ClassVar[str] = "pysandboxes-vm-"

    @abstractmethod
    def guest_run_dir_mount(self) -> str:
        """Guest path where the host run directory is mounted (e.g. virtio-9p)."""

    @abstractmethod
    def augment_rules_for_guest_run_mount(self, all_rules: AllRules) -> AllRules:
        """Return ``all_rules`` with implicit bind for host tmp ↔ guest run mount."""

    @staticmethod
    def show_boot_console_truthy(all_rules: Any | None) -> bool:
        """Whether the profile requests full VM serial / verbose bootstrap (truthy ``show_boot_console``)."""
        if all_rules is None:
            return False
        params = getattr(all_rules, "os_sandbox_params", None)
        if not params:
            return False
        raw = str(params.get("show_boot_console", "false")).strip().lower()
        return raw in ("true", "1", "yes")

    async def wait_process_and_filter_console(
        self,
        process: asyncio.subprocess.Process,
        *,
        forward_all: bool = False,
        tee_file: TextIO | None = None,
    ) -> int:
        """Drain VM stdout/stderr with sentinel filtering; wait for process exit."""
        return await qemu_wait_and_filter_console(
            process,
            forward_all=forward_all,
            tee_file=tee_file,
        )

    def read_guest_exitcode(self, exitcode_file: Path) -> int | None:
        """Read guest-written exit code from the shared run dir (short polling)."""
        return read_qemu_guest_exitcode(exitcode_file)
