# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Configuration parameters for remote execution components.

This module defines timing constants and configuration parameters used
by the remote execution system for daemon management, connection handling,
and process lifecycle control.

All timing values are in seconds unless otherwise specified.
"""

# Polling and retry configuration
POLLING_DELAY = 0.1  # Base delay between polling operations
INTERVAL_FOR_RETRY_CONNECTION = 0.5  # Connection retry delay
MAX_CONNECT_RETRY = 5  # Maximum connection attempts before raising error

# Start and lifecycle timing
INTERVAL_FOR_PING_DAEMON = POLLING_DELAY * 2  # Daemon ping interval
TIMEOUT_FOR_PING = 1.0  # FIX_RELEASE 1.0  # Ping response timeout
LOOP_FOR_PING = 100  # FIX_RELEASE 100 # Try to ping how many time?

# Shutdown and lifecycle timing
TIMEOUT_GRACEFUL_SHUTDOWN = 1  # 1 FIX_RELEASE Graceful shutdown timeout
TIMEOUT_FOR_STOP_DAEMON = TIMEOUT_GRACEFUL_SHUTDOWN * 2  # Daemon stop timeout

# Exponential backoff retry configuration
RETRY_RESET_DELAY = 3 * 60.0  # Delay to reset connection attempt counters
RETRY_MAX_ATTEMPTS = 5  # Maximum retry attempts in reset period
RETRY_BASE_DELAY = 1.0  # Initial exponential backoff delay
RETRY_FACTOR = 1.5  # Exponential backoff multiplier
RETRY_MAX_DELAY = 5.0  # Maximum exponential backoff delay cap
