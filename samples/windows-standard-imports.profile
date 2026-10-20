# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
# Windows modules imported by filelock and the other dependencies of the samples.
python-import=msvcrt, ctypes, _ctypes, nt, _winapi, winreg, _overlapped, ntpath, nturl2path, pywintypes, _win32sysloader, pywin32_system32, win32api, win32con, win32job, win32file, winerror
env=LOCALAPPDATA=${LOCALAPPDATA}
env=APPDATA=${APPDATA}
env=USERPROFILE=${USERPROFILE}
env=SYSTEMROOT=${SYSTEMROOT}
env=COMSPEC=${COMSPEC}
python-api=ALLOW:ctypes.CDLL
python-api=ALLOW:_ctypes.LoadLibrary
