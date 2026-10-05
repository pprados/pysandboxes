# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Pickle-friendly daemon config shared between host and guest.

Kept free of aiohttp and other heavy remote imports so ``main_sandbox`` can load
in minimal environments (e.g. QEMU guest) without pulling the full SSE client stack.

Do **not** import ``all_rules`` at module level: that pulls every guard module and
native-heavy dependency chains at import time and can SIGSEGV in the QEMU guest.
"""

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from ..all_rules import AllRules


class DaemonParameters(NamedTuple):
    """Configuration parameters for daemon processes.

    To assist in scenarios where there is no sandbox initialization function, we propagate the main log
    parameters as default behavior.

    Attributes:
        all_rules: Security rules configuration.
        log_level: Logging level for the daemon.
        log_format: Format string for log messages.
        use_rich_handler: Use Rich Handler
        token: Authentication token for communication.
        port: Network port for communication.
        init_fn: Initialization function reference.
        netfilter_rules: Optional iptables rules the child applies itself: the QEMU guest, where it is root;
            default empty. bwrap gets none: the host loads its filter.
        python_main_args: For VM guest: argv to run as main (e.g. ["-m", "module"]); default empty.
        guest_run_dir: QEMU guest path where the host run directory is
            mounted; the guest writes its exit code there.
        guest_working_dir: Host working directory at QEMU launch; the guest
            bootstrap moves there so relative rules such as ``expose-rw=./tmp``
            designate the same files on both sides.
    """

    all_rules: "AllRules"
    log_level: int
    log_format: str
    use_rich_handler: bool
    token: str
    port: int
    init_fn: str
    netfilter_rules: tuple[str, ...] = ()
    python_main_args: tuple[str, ...] = ()
    # For QEMU python_sb: guest path where host run dir is mounted; guest writes exit code there
    guest_run_dir: str | None = None
    # Host cwd at QEMU launch; guest bootstrap cds here so relative paths match expose-rw=./tmp etc.
    guest_working_dir: str | None = None
