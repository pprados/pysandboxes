"""Configuration parameters for remote execution components.

This module defines timing constants and configuration parameters used
by the remote execution system for daemon management, connection handling,
and process lifecycle control.

All timing values are in seconds unless otherwise specified.
"""

# Polling and retry configuration
POLLING_DELAY = 0.1  # Base delay between polling operations
INTERVAL_FOR_PING_DAEMON = POLLING_DELAY * 2  # Daemon ping interval
INTERVAL_FOR_RETRY_CONNECTION = 0.5  # Connection retry delay
MAX_CONNECT_RETRY = 5  # Maximum connection attempts before raising error

# Shutdown and lifecycle timing
TIMEOUT_GRACEFUL_SHUTDOWN = 1  # Graceful shutdown timeout
TIMEOUT_FOR_STOP_DAEMON = TIMEOUT_GRACEFUL_SHUTDOWN * 2  # Daemon stop timeout
TIMEOUT_FOR_PING = 1  # Ping response timeout

# Exponential backoff retry configuration
RETRY_RESET_DELAY = 3 * 60  # Delay to reset connection attempt counters
RETRY_MAX_ATTEMPTS = 5  # Maximum retry attempts in reset period
RETRY_BASE_DELAY = 1  # Initial exponential backoff delay
RETRY_FACTOR = 1.5  # Exponential backoff multiplier
RETRY_MAX_DELAY = 5  # Maximum exponential backoff delay cap
