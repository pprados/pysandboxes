# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Abstract base for VM-based SSE daemons (e.g. QEMU).

VMSSEDaemon extends BaseSubProcessDaemon for providers whose "subprocess" is
a VM process (e.g. QEMU) rather than a Python process. Subclasses must
override _re_start_cmd to call launch_sandbox(args, pipe_path=..., ...) with
args only — do not append ["--_named-pipe", str(pipe_path)] to args; the guest
receives config by provider-specific means (e.g. HTTP from host).
"""

from .sse_client_subprocess_daemon import BaseSubProcessDaemon

__all__ = ["VMSSEDaemon"]


class VMSSEDaemon(BaseSubProcessDaemon):
    """Base class for VM-based sandbox daemons (e.g. QEMU).

    The "subprocess" is the VM process (e.g. qemu-system-x86_64). Configuration
    is passed to the guest by provider-specific means. Subclasses must override
    _re_start_cmd to pass the VM command line only to launch_sandbox (no
    --_named-pipe args appended).
    """

    __slots__ = ()  # No additional slots; use parent's
