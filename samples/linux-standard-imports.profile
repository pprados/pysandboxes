# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Linux imports and native loader calls required by Strands dependencies.
python-import=ctypes, _ctypes
python-api=ALLOW:ctypes.CDLL
python-api=ALLOW:_ctypes.dlopen
