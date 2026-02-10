import os

# HOST = os.environ.get("HOST", "127.0.0.1")
HOST = os.environ.get("HOST", "localhost")
PORT = int(os.environ.get("PORT", 8000))
PATH_RPC = os.environ.get("PATH_RPC", "/rpc")
DELAY_FOR_STOP_DAEMON = 5000  # FIXME: DELAY_FOR_STOP_DAEMON
DELAY_FOR_CALL_DAEMON = 1  # 0.5
INTERVAL_FOR_PING_DAEMON=0.4
