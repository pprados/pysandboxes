# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Configuration parameters for remote execution components.

This module defines timing constants and configuration parameters used
by the remote execution system for daemon management, connection handling,
and process lifecycle control.

All timing values are in seconds unless otherwise specified.
"""

import logging
from typing import Any, Mapping

from .qemu_image import qemu_accel_args

logger = logging.getLogger(__name__)

# Polling and retry configuration
POLLING_DELAY = 0.1  # Base delay between polling operations
INTERVAL_FOR_RETRY_CONNECTION = 0.5  # Connection retry delay
MAX_CONNECT_RETRY = 5  # Maximum connection attempts before raising error

# Start and lifecycle timing
INTERVAL_FOR_PING_DAEMON = POLLING_DELAY * 2  # Daemon ping interval
TIMEOUT_FOR_PING = 1.0  # Ping response timeout
LOOP_FOR_PING = 100  # Try to ping how many times?

# Start daemon timeout (sync start_daemon() wait for async start to complete)
TIMEOUT_FOR_START_DAEMON = 30  # seconds
# QEMU needs VM boot (QEMU_BOOT_DELAY) + ping loop; allow up to 90s
TIMEOUT_FOR_START_DAEMON_QEMU = 90  # seconds
# Emulated, the same guest was measured answering at ~125s; leave a margin over that.
TIMEOUT_FOR_START_DAEMON_QEMU_TCG = 180  # seconds


def qemu_start_timeout(os_sandbox_params: Mapping[str, Any]) -> float:
    """Seconds the QEMU daemon gets to answer, from the ``qemu.start_timeout`` rule.

    Without the rule the default follows the acceleration actually in use, because that
    is what sets the order of magnitude: a KVM boot leaves room to spare inside 90s -- a
    whole partial-mode run takes ~22s -- where the same guest emulated was measured
    answering at ~125s and needs the longer default. A container is normally not given
    /dev/kvm, and that is exactly the case that could not start a daemon at all.

    The condition is ``qemu_accel_args``, the very function that decides whether QEMU is
    given ``-enable-kvm``, so the delay cannot disagree with how the VM really runs.
    """
    raw = os_sandbox_params.get("start_timeout")
    default = float(
        TIMEOUT_FOR_START_DAEMON_QEMU if qemu_accel_args(os_sandbox_params) else TIMEOUT_FOR_START_DAEMON_QEMU_TCG
    )
    if raw is None:
        return default
    try:
        timeout = float(str(raw).strip())
    except ValueError:
        timeout = 0.0
    if timeout <= 0:
        logger.warning(
            "Ignoring qemu.start_timeout=%r: expected a positive number of seconds; using %ss",
            raw,
            default,
        )
        return default
    return timeout


# RPC call timeout (prevents infinite block if guest never responds)
TIMEOUT_FOR_RPC_CALL = 120  # seconds

# Shutdown and lifecycle timing
TIMEOUT_GRACEFUL_SHUTDOWN = 2  # Graceful shutdown timeout
TIMEOUT_FOR_STOP_DAEMON = TIMEOUT_GRACEFUL_SHUTDOWN * 2  # Daemon stop timeout

# Exponential backoff retry configuration
RETRY_RESET_DELAY = 3 * 60.0  # Delay to reset connection attempt counters
RETRY_MAX_ATTEMPTS = 5  # Maximum retry attempts in reset period
RETRY_BASE_DELAY = 1.0  # Initial exponential backoff delay
RETRY_FACTOR = 1.5  # Exponential backoff multiplier
RETRY_MAX_DELAY = 5.0  # Maximum exponential backoff delay cap
