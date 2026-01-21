import os

# HOST = os.environ.get("HOST", "127.0.0.1")
HOST = os.environ.get("HOST", "localhost")
PORT = int(os.environ.get("PORT", 8000))
PATH_RPC = os.environ.get("PATH_RPC", "/rpc")
DELAY_FOR_START_DAEMON = 0.4
