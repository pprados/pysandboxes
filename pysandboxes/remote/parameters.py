import os

POLLING_DELAY = 0.1
INTERVAL_FOR_PING_DAEMON = POLLING_DELAY
TIMEOUT_GRACEFUL_SHUTDOWN = 1  # After, force the exit
TIMEOUT_FOR_STOP_DAEMON = TIMEOUT_GRACEFUL_SHUTDOWN * 2
TIMEOUT_FOR_PING = 1
TIMEOUT_BEFORE_KILL_DAEMON = 1

RETRY_MAX_ATTEMPTS = 5  # Maximum number of retry _attempts
RETRY_BASE_DELAY = 0.1  # Initial delay in seconds (e.g., 100 ms)
RETRY_FACTOR = 2.0  # Exponential increase _factor
RETRY_MAX_DELAY = 10  # Maximum delay in seconds
RETRY_RESET_DELAY = 120.0  # delay to reset attemps
