import os

# HOST = os.environ.get("HOST", "127.0.0.1")
HOST = os.environ.get("SB_HOST", "localhost")
PORT = int(os.environ.get("SB_PORT", 8000))  # FIXME: port 8000 ?
PATH_RPC = os.environ.get("SB_PATH_RPC", "/rpc")
DELAY_FOR_STOP_DAEMON = 5000  # FIXME: DELAY_FOR_STOP_DAEMON
DELAY_FOR_CALL_DAEMON = 1  # 0.5
INTERVAL_FOR_PING_DAEMON=0.4

RETRY_MAX_ATTEMPTS=1  # FIXME: 5 Maximum number of retry _attempts
RETRY_BASE_DELAY=0.1  # Initial delay in seconds (e.g., 100 ms)
RETRY_FACTOR=2.0  # Exponential increase _factor
RETRY_MAX_DELAY=10 # Maximum delay in seconds
RETRY_RESET_DELAY=120.0  # delay to reset attemps