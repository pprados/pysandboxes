# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Windows standard modules and UTF-8 output for sample subprocesses.
python-import=msvcrt, _winapi, nt, pywintypes, _win32sysloader, pywin32_system32
python-import=win32api, win32con, win32job, win32event, win32file, win32pipe, winerror
python-import=win32com, pythoncom
python-import=ctypes, _ctypes
python-api=ALLOW:ctypes.CDLL
python-api=ALLOW:_ctypes.LoadLibrary
env=PYTHONUTF8=1
env=LOCALAPPDATA=${LOCALAPPDATA:-/tmp}
env=APPDATA=${APPDATA:-/tmp}
env=USERPROFILE=${USERPROFILE:-/tmp}
env=WIN_PD_OVERRIDE_APPDATA=${APPDATA:-/tmp}
env=WIN_PD_OVERRIDE_LOCAL_APPDATA=${LOCALAPPDATA:-/tmp}
