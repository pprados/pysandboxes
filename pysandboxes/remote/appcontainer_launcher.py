# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Trusted Windows trampoline that starts the sandbox process in an AppContainer."""

import argparse
import ctypes
import json
import socket
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

from .appcontainer_acl import (
    ACLGrant,
    apply_acl,
    begin_run,
    finish_run,
    mark_window_access,
    mask_acl,
    release_run_lock,
)
from .win_job import assign, close, create_kill_on_close_job, set_ui_restrictions
from .win_window import grant_service_window_access

_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_CREATE_SUSPENDED = 0x00000004
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_INFINITE = 0xFFFFFFFF


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _SecurityCapabilities(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(_SidAndAttributes)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class _StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _StartupInfoEx(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", ctypes.c_void_p)]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _win_error() -> OSError:
    return ctypes.__dict__["WinError"](ctypes.__dict__["get_last_error"]())


def _win_dll(name: str) -> Any:
    if sys.platform != "win32":
        raise OSError("AppContainer launcher is available only on win32")
    return ctypes.__dict__["WinDLL"](name, use_last_error=True)


def _sid_string(sid: ctypes.c_void_p) -> str:
    kernel32 = _win_dll("kernel32")
    advapi32 = _win_dll("advapi32")
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    string_sid = wintypes.LPWSTR()
    advapi32.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(string_sid)):
        raise _win_error()
    try:
        return string_sid.value or ""
    finally:
        kernel32.LocalFree(string_sid)


def _capability_sid(name: str) -> ctypes.c_void_p:
    kernelbase = _win_dll("kernelbase")
    local_free = _win_dll("kernel32").LocalFree
    local_free.argtypes = (ctypes.c_void_p,)
    local_free.restype = ctypes.c_void_p
    groups = ctypes.POINTER(ctypes.c_void_p)()
    group_count = wintypes.DWORD()
    capabilities = ctypes.POINTER(ctypes.c_void_p)()
    capability_count = wintypes.DWORD()
    derive = kernelbase.DeriveCapabilitySidsFromName
    derive.argtypes = (
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
        ctypes.POINTER(wintypes.DWORD),
    )
    derive.restype = wintypes.BOOL
    if not derive(
        name,
        ctypes.byref(groups),
        ctypes.byref(group_count),
        ctypes.byref(capabilities),
        ctypes.byref(capability_count),
    ):
        raise _win_error()
    try:
        if not capability_count.value:
            raise OSError(f"Windows returned no SID for capability {name!r}")
        sid = capabilities[0]
        capabilities[0] = None
        return sid
    finally:
        for index in range(group_count.value):
            local_free(groups[index])
        for index in range(capability_count.value):
            if capabilities[index]:
                local_free(capabilities[index])
        if groups:
            local_free(groups)
        if capabilities:
            local_free(capabilities)


def _create_profile(name: str) -> tuple[ctypes.c_void_p, str]:
    userenv = _win_dll("userenv")
    sid = ctypes.c_void_p()
    create = userenv.CreateAppContainerProfile
    create.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    )
    create.restype = ctypes.c_long
    hr = create(name, name, "PySandboxes per-run sandbox", None, 0, ctypes.byref(sid))
    if hr & 0x80000000:
        raise OSError(f"CreateAppContainerProfile failed with HRESULT 0x{hr & 0xFFFFFFFF:08X}")
    try:
        return sid, _sid_string(sid)
    except BaseException:
        _win_dll("kernel32").LocalFree(sid)
        _delete_profile(name)
        raise


def _delete_profile(name: str) -> None:
    userenv = _win_dll("userenv")
    delete = userenv.DeleteAppContainerProfile
    delete.argtypes = (wintypes.LPCWSTR,)
    delete.restype = ctypes.c_long
    hr = delete(name)
    if hr & 0x80000000:
        raise OSError(f"DeleteAppContainerProfile failed with HRESULT 0x{hr & 0xFFFFFFFF:08X}")


def _create_process(
    command: list[str], env: dict[str, str], package_sid: ctypes.c_void_p, capability_sids: list[ctypes.c_void_p]
) -> _ProcessInformation:
    kernel32 = _win_dll("kernel32")
    capability_array = (_SidAndAttributes * len(capability_sids))(
        *(_SidAndAttributes(sid, 0x00000004) for sid in capability_sids)
    )
    security_capabilities = _SecurityCapabilities(package_sid, capability_array, len(capability_sids), 0)
    size = ctypes.c_size_t()
    initialize = kernel32.InitializeProcThreadAttributeList
    initialize.argtypes = (ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t))
    initialize.restype = wintypes.BOOL
    kernel32.DeleteProcThreadAttributeList.argtypes = (ctypes.c_void_p,)
    kernel32.DeleteProcThreadAttributeList.restype = None
    if initialize(None, 1, 0, ctypes.byref(size)) or ctypes.__dict__["get_last_error"]() != 122:
        raise _win_error()
    attribute_buffer = ctypes.create_string_buffer(size.value)
    attribute_list = ctypes.cast(attribute_buffer, ctypes.c_void_p)
    if not initialize(attribute_list, 1, 0, ctypes.byref(size)):
        raise _win_error()
    update = kernel32.UpdateProcThreadAttribute
    update.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )
    update.restype = wintypes.BOOL
    if not update(
        attribute_list,
        0,
        _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
        ctypes.byref(security_capabilities),
        ctypes.sizeof(security_capabilities),
        None,
        None,
    ):
        kernel32.DeleteProcThreadAttributeList(attribute_list)
        raise _win_error()
    startup = _StartupInfoEx()
    startup.StartupInfo.cb = ctypes.sizeof(startup)
    startup.lpAttributeList = attribute_list
    info = _ProcessInformation()
    sorted_env = sorted(env.items(), key=lambda item: item[0].upper())
    environment = "\0".join(f"{key}={value}" for key, value in sorted_env) + "\0\0"
    env_buffer = ctypes.create_unicode_buffer(environment)
    cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
    create = kernel32.CreateProcessW
    create.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfoEx),
        ctypes.POINTER(_ProcessInformation),
    )
    create.restype = wintypes.BOOL
    flags = _CREATE_SUSPENDED | _EXTENDED_STARTUPINFO_PRESENT | _CREATE_UNICODE_ENVIRONMENT
    try:
        if not create(
            command[0],
            cmdline,
            None,
            None,
            False,
            flags,
            env_buffer,
            None,
            ctypes.byref(startup),
            ctypes.byref(info),
        ):
            error = _win_error()
            raise OSError(
                f"{error} (environment keys: {', '.join(sorted(env))}; "
                f"LOCALAPPDATA={'present' if env.get('LOCALAPPDATA') else 'missing'})"
            ) from error
    finally:
        kernel32.DeleteProcThreadAttributeList(attribute_list)
    return info


def run(plan_path: Path, config_path: Path, python_args: list[str] | None = None) -> int:
    if sys.platform != "win32":
        raise OSError("AppContainer launcher is available only on win32")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    name = str(plan["profile_name"])
    package_sid_ptr, package_sid = _create_profile(name)
    capability_sids: list[ctypes.c_void_p] = []
    job: int | None = None
    process_info: _ProcessInformation | None = None
    listener: socket.socket | None = None
    run_lock: Any | None = None
    completed = False
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        runtime_sid_ptr = _capability_sid("pysandboxesRuntime")
        capability_sids.append(runtime_sid_ptr)
        runtime_sid = _sid_string(runtime_sid_ptr)
        run_lock = begin_run(package_sid, name)
        for capability in plan["capabilities"]:
            capability_sids.append(_capability_sid(capability))
        grants = [ACLGrant(Path(item["path"]), item["rights"], item["sid_kind"]) for item in plan["grants"]]
        for grant in grants:
            if grant.rights == "MASK":
                mask_acl(grant.path, package_sid, runtime_sid)
            else:
                sid = runtime_sid if grant.sid_kind == "runtime" else package_sid
                apply_acl(
                    grant.path,
                    sid,
                    grant.rights,
                    runtime=grant.sid_kind == "runtime",
                    run_sid=package_sid,
                )
        apply_acl(config_path, package_sid, "M", run_sid=package_sid)
        for path in (Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()):
            if not any(grant.path.resolve() == path and grant.sid_kind == "runtime" for grant in grants):
                apply_acl(path, runtime_sid, "RX", runtime=True)
        mark_window_access(package_sid)
        grant_service_window_access(package_sid)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", int(plan["port"])))
        listener.listen(socket.SOMAXCONN)
        child_command = [*plan["child_command"], *(python_args or []), "--_named-pipe", str(config_path)]
        shared_path = Path(plan["shared_socket_path"])
        child_command.extend(("--_shared-socket", str(shared_path)))
        process_info = _create_process(child_command, dict(plan["env"]), package_sid_ptr, capability_sids)
        job = create_kill_on_close_job()
        assign(job, process_info.dwProcessId)
        set_ui_restrictions(job)
        shared_path.write_bytes(listener.share(process_info.dwProcessId))
        kernel32 = _win_dll("kernel32")
        kernel32.ResumeThread.argtypes = (wintypes.HANDLE,)
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel32.CloseHandle.restype = wintypes.BOOL
        if kernel32.ResumeThread(process_info.hThread) == 0xFFFFFFFF:
            raise _win_error()
        if kernel32.WaitForSingleObject(process_info.hProcess, _INFINITE) == 0xFFFFFFFF:
            raise _win_error()
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(exit_code)):
            raise _win_error()
        completed = True
        return int(exit_code.value)
    finally:
        pending_error = sys.exc_info()[1]
        cleanup_errors: list[Exception] = []

        def cleanup(action: Any, *args: Any) -> None:
            try:
                action(*args)
            except Exception as error:  # Cleanup every resource before reporting failures.
                cleanup_errors.append(error)

        if listener is not None:
            cleanup(listener.close)
        if job is not None:
            cleanup(close, job)
        if process_info is not None:
            kernel32 = _win_dll("kernel32")
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            if not completed:
                kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
                kernel32.TerminateProcess.restype = wintypes.BOOL
                cleanup(kernel32.TerminateProcess, process_info.hProcess, 1)
            cleanup(kernel32.CloseHandle, process_info.hThread)
            cleanup(kernel32.CloseHandle, process_info.hProcess)
        if run_lock is not None:
            profiles: tuple[str, ...] = ()
            try:
                profiles = finish_run(package_sid)
            except Exception as error:
                cleanup_errors.append(error)
            for profile in profiles:
                cleanup(_delete_profile, profile)
            if name not in profiles:
                cleanup(_delete_profile, name)
            cleanup(release_run_lock, run_lock)
        kernel32 = _win_dll("kernel32")
        kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel32.LocalFree.restype = ctypes.c_void_p
        for sid in capability_sids:
            cleanup(kernel32.LocalFree, sid)
        cleanup(kernel32.LocalFree, package_sid_ptr)
        if run_lock is None:
            cleanup(_delete_profile, name)
        if cleanup_errors:
            message = "AppContainer cleanup failed: " + "; ".join(str(error) for error in cleanup_errors)
            if pending_error is not None:
                pending_error.add_note(message)
            else:
                raise ExceptionGroup(message, cleanup_errors)


def main() -> int:
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("plan")
    parser.add_argument("--_named-pipe", required=True)
    args, python_args = parser.parse_known_args()
    return run(Path(args.plan), Path(args._named_pipe), python_args)


if __name__ == "__main__":
    raise SystemExit(main())
