# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# macOS imports and native loader calls required by sample dependencies.
# ctypes.CDLL and _ctypes.dlopen permit loading native code.
python-import=ctypes, _ctypes
python-api=ALLOW:ctypes.CDLL
python-api=ALLOW:_ctypes.dlopen
