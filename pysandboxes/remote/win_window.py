# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Temporary minimal window-station and desktop access for service sessions."""

import ctypes
import sys
from ctypes import wintypes
from typing import Any

from .appcontainer_acl import _acl_lock

_SE_WINDOW_OBJECT = 7
_DACL_SECURITY_INFORMATION = 0x00000004
_UOI_NAME = 2
_GRANT_ACCESS = 1
_REVOKE_ACCESS = 4
_TRUSTEE_IS_SID = 0
_TRUSTEE_IS_USER = 1
_WINSTA_ACCESSGLOBALATOMS = 0x0020
_WINSTA_READATTRIBUTES = 0x0002
_DESKTOP_READOBJECTS = 0x0001


class _Trustee(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", ctypes.c_void_p),
        ("MultipleTrusteeOperation", wintypes.INT),
        ("TrusteeForm", wintypes.INT),
        ("TrusteeType", wintypes.INT),
        ("ptstrName", ctypes.c_void_p),
    ]


class _ExplicitAccess(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", wintypes.DWORD),
        ("grfAccessMode", wintypes.INT),
        ("grfInheritance", wintypes.DWORD),
        ("Trustee", _Trustee),
    ]


def _win_dll(name: str) -> Any:
    if sys.platform != "win32":
        raise OSError("Window station access is available only on win32")
    return ctypes.__dict__["WinDLL"](name, use_last_error=True)


def _window_name(user32: Any, handle: int) -> str:
    size = wintypes.DWORD()
    user32.GetUserObjectInformationW.argtypes = (
        wintypes.HANDLE,
        wintypes.INT,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    user32.GetUserObjectInformationW(handle, _UOI_NAME, None, 0, ctypes.byref(size))
    name = ctypes.create_unicode_buffer((size.value + 1) // ctypes.sizeof(ctypes.c_wchar))
    if not user32.GetUserObjectInformationW(handle, _UOI_NAME, name, size.value, ctypes.byref(size)):
        raise ctypes.__dict__["WinError"](ctypes.__dict__["get_last_error"]())
    return name.value


def _change_access(handle: int, sid_text: str, rights: int, add: bool) -> None:
    advapi32 = _win_dll("advapi32")
    kernel32 = _win_dll("kernel32")
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    sid = ctypes.c_void_p()
    convert = advapi32.ConvertStringSidToSidW
    convert.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p))
    convert.restype = wintypes.BOOL
    if not convert(sid_text, ctypes.byref(sid)):
        raise ctypes.__dict__["WinError"](ctypes.__dict__["get_last_error"]())
    old_acl = ctypes.c_void_p()
    security_descriptor = ctypes.c_void_p()
    new_acl = ctypes.c_void_p()
    get_security = advapi32.GetSecurityInfo
    get_security.argtypes = (
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    get_security.restype = wintypes.DWORD
    set_entries = advapi32.SetEntriesInAclW
    set_entries.argtypes = (
        wintypes.ULONG,
        ctypes.POINTER(_ExplicitAccess),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    set_entries.restype = wintypes.DWORD
    set_security = advapi32.SetSecurityInfo
    set_security.argtypes = (
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    set_security.restype = wintypes.DWORD
    trustee = _Trustee(None, 0, _TRUSTEE_IS_SID, _TRUSTEE_IS_USER, sid)
    access = _ExplicitAccess(rights, _GRANT_ACCESS if add else _REVOKE_ACCESS, 0, trustee)
    try:
        status = get_security(
            handle,
            _SE_WINDOW_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(old_acl),
            None,
            ctypes.byref(security_descriptor),
        )
        if status:
            raise ctypes.__dict__["WinError"](status)
        status = set_entries(1, ctypes.byref(access), old_acl, ctypes.byref(new_acl))
        if status:
            raise ctypes.__dict__["WinError"](status)
        status = set_security(
            handle,
            _SE_WINDOW_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            new_acl,
            None,
        )
        if status:
            raise ctypes.__dict__["WinError"](status)
    finally:
        if new_acl:
            kernel32.LocalFree(new_acl)
        if security_descriptor:
            kernel32.LocalFree(security_descriptor)
        kernel32.LocalFree(sid)


def grant_service_window_access(package_sid: str) -> bool:
    """Grant minimal UI initialization rights outside the interactive WinSta0."""
    user32 = _win_dll("user32")
    kernel32 = _win_dll("kernel32")
    user32.GetProcessWindowStation.restype = wintypes.HANDLE
    user32.GetThreadDesktop.argtypes = (wintypes.DWORD,)
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    user32.GetProcessWindowStation.argtypes = ()
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.GetUserObjectInformationW.argtypes = (
        wintypes.HANDLE,
        wintypes.INT,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    station = user32.GetProcessWindowStation()
    desktop = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    if not station or not desktop:
        raise ctypes.__dict__["WinError"](ctypes.__dict__["get_last_error"]())
    if _window_name(user32, station).casefold() == "winsta0":
        return False
    with _acl_lock():
        _change_access(station, package_sid, _WINSTA_ACCESSGLOBALATOMS | _WINSTA_READATTRIBUTES, True)
        try:
            _change_access(desktop, package_sid, _DESKTOP_READOBJECTS, True)
        except BaseException:
            _change_access(station, package_sid, _WINSTA_ACCESSGLOBALATOMS | _WINSTA_READATTRIBUTES, False)
            raise
    return True


def remove_service_window_access(package_sid: str, *, locked: bool = False) -> None:
    """Remove the temporary window-station and desktop ACEs for one package SID."""
    user32 = _win_dll("user32")
    kernel32 = _win_dll("kernel32")
    user32.GetProcessWindowStation.restype = wintypes.HANDLE
    user32.GetThreadDesktop.argtypes = (wintypes.DWORD,)
    user32.GetThreadDesktop.restype = wintypes.HANDLE
    user32.GetProcessWindowStation.argtypes = ()
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.GetProcessWindowStation.argtypes = ()
    station = user32.GetProcessWindowStation()
    desktop = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
    if not station or not desktop:
        raise ctypes.__dict__["WinError"](ctypes.__dict__["get_last_error"]())
    if _window_name(user32, station).casefold() == "winsta0":
        return

    def remove() -> None:
        _change_access(desktop, package_sid, _DESKTOP_READOBJECTS, False)
        _change_access(station, package_sid, _WINSTA_ACCESSGLOBALATOMS | _WINSTA_READATTRIBUTES, False)

    if locked:
        remove()
    else:
        with _acl_lock():
            remove()
