# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Linux imports and native loader calls required by sample dependencies.
# These imports and API grants match the existing sample permissions.
python-import=ctypes, _ctypes
python-api=ALLOW:ctypes.CDLL
python-api=ALLOW:_ctypes.LoadLibrary
