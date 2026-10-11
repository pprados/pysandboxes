# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Small, lazily-bound Win32 Job Object helpers."""

import ctypes
import sys
from ctypes import wintypes
from typing import Any

_UI_LIMIT_FLAGS = 0x00000001 | 0x00000002 | 0x00000004 | 0x00000008 | 0x00000020 | 0x00000040 | 0x00000080


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_longlong),
        ("PerJobUserTimeLimit", ctypes.c_longlong),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _win_error() -> OSError:
    error_code = ctypes.__dict__["get_last_error"]()
    return ctypes.__dict__["WinError"](error_code)


def _kernel32() -> Any:
    if sys.platform != "win32":
        raise OSError("Windows Job Objects are available only on win32")
    return ctypes.__dict__["WinDLL"]("kernel32", use_last_error=True)


def create_kill_on_close_job() -> int:
    """Create a Job Object that terminates its processes when its handle closes."""
    kernel32 = _kernel32()
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, wintypes.INT, ctypes.c_void_p, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise _win_error()
    info = _ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
        error = ctypes.__dict__["get_last_error"]()
        kernel32.CloseHandle(handle)
        raise ctypes.__dict__["WinError"](error)
    return int(handle)


def assign(job: int, pid: int) -> None:
    """Assign a process to a Job Object, raising if Windows refuses the assignment."""
    kernel32 = _kernel32()
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    process = kernel32.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
    if not process:
        raise _win_error()
    try:
        if not kernel32.AssignProcessToJobObject(job, process):
            raise _win_error()
    finally:
        kernel32.CloseHandle(process)


def set_ui_restrictions(job: int) -> None:
    """Restrict clipboard, desktop, global atoms, and system UI operations in a job."""
    kernel32 = _kernel32()
    kernel32.SetInformationJobObject.argtypes = (wintypes.HANDLE, wintypes.INT, ctypes.c_void_p, wintypes.DWORD)
    restrictions = wintypes.DWORD(_UI_LIMIT_FLAGS)
    if not kernel32.SetInformationJobObject(job, 4, ctypes.byref(restrictions), ctypes.sizeof(restrictions)):
        raise _win_error()


def close(job: int) -> None:
    """Close a Job Object handle; KILL_ON_JOB_CLOSE terminates remaining members."""
    kernel32 = _kernel32()
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    if not kernel32.CloseHandle(job):
        raise _win_error()
