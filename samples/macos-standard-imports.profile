# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# macOS native loader calls required by filelock, which a dependency of the samples imports.
python-import=ctypes, _ctypes
python-api=ALLOW:ctypes.CDLL
python-api=ALLOW:_ctypes.dlopen
