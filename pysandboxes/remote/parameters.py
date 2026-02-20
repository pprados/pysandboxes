# all times are in second
POLLING_DELAY = 0.1  # For all polling, delay between retry
INTERVAL_FOR_PING_DAEMON = POLLING_DELAY * 2
INTERVAL_FOR_RETRY_CONNECTION = 0.5
MAX_CONNECT_RETRY = 5  # Else, raise a RuntimeError
TIMEOUT_GRACEFUL_SHUTDOWN = 1  # After, force the exit
TIMEOUT_FOR_STOP_DAEMON = TIMEOUT_GRACEFUL_SHUTDOWN * 2
TIMEOUT_FOR_PING = 1  # Delay between ping

RETRY_RESET_DELAY = 3 * 60  # delay to reset attempts
RETRY_MAX_ATTEMPTS = 5  # Maximum number of retry in RETRY_RESET_DELAY else exit(-1)
RETRY_BASE_DELAY = 1  # Initial delay in seconds (e.g., 100 ms)
RETRY_FACTOR = 1.5  # Exponential increase factor (delay=delay*factor)
RETRY_MAX_DELAY = 5  # Maximum delay in seconds, but no more of max delay
