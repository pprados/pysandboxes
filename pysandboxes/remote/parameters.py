import os

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", 8000))
PATH_RPC = os.environ.get("PATH_RPC", "/rpc")
DELAY_FOR_START_DAEMON = 0 # FIXME 0.5: c'est ok pour task daemon. Résoudre pour process
