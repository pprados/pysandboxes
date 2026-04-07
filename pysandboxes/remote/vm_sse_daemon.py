# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Abstract base for VM-based SSE daemons (e.g. QEMU).

VMSSEDaemon extends BaseSubProcessDaemon for providers whose "subprocess" is
a VM process (e.g. QEMU) rather than a Python process. Subclasses must
override _re_start_cmd to call launch_sandbox(args, pipe_path=..., ...) with
args only — do not append ["--_named-pipe", str(pipe_path)] to args, since
the VM binary does not accept those; the guest inside the VM reads the pipe
via a mounted directory (e.g. virtio-9p).
"""

from .sse_client_subprocess_daemon import BaseSubProcessDaemon

__all__ = ["VMSSEDaemon"]


class VMSSEDaemon(BaseSubProcessDaemon):
    """Base class for VM-based sandbox daemons (e.g. QEMU).

    The "subprocess" is the VM process (e.g. qemu-system-x86_64). Configuration
    is still written to the named pipe by the host; the guest reads it via a
    mount (e.g. 9p). Subclasses must override _re_start_cmd to pass the VM
    command line only to launch_sandbox (no --_named-pipe args appended).
    """

    __slots__ = ()  # No additional slots; use parent's
