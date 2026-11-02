# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Pure planning helpers for the Windows AppContainer access-control layer."""

import base64
import ctypes
import errno
import glob
import os
import site
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..all_rules import AllRules
from ..guard_files import FSExposeRule, IgnoreRule
from ..guard_socket import Action, Direction, SocketRule


@dataclass(frozen=True)
class ACLGrant:
    """A filesystem access grant to one AppContainer identity."""

    path: Path
    rights: str
    sid_kind: str


def build_acl_plan(all_rules: AllRules, temp: Path) -> tuple[ACLGrant, ...]:
    """Map filesystem rules and Python runtime paths to package or runtime grants."""
    grants: dict[tuple[Path, str], ACLGrant] = {}

    def add(path: str | Path, rights: str, sid_kind: str) -> None:
        normalized = Path(path).resolve(strict=False)
        grants[(normalized, sid_kind)] = ACLGrant(normalized, rights, sid_kind)

    add(sys.base_prefix, "RX", "runtime")
    add(sys.prefix, "RX", "runtime")
    for entry in (
        *sys.path,
        *site.getsitepackages(),
        site.getusersitepackages(),
        *all_rules.envs.get("PYTHONPATH", "").split(os.pathsep),
        os.getcwd(),
    ):
        if entry:
            path = Path(entry)
            runtime_paths = (Path(sys.base_prefix), Path(sys.prefix))
            if path.exists() and not any(_is_relative_to(path, runtime) for runtime in runtime_paths):
                add(path, "RX", "package")
    for rule in all_rules.file_rules:
        if isinstance(rule, FSExposeRule):
            add(rule.path, "M" if rule.write else "RX", "package")
        elif isinstance(rule, IgnoreRule):
            for match in glob.glob(rule.source, recursive=True):
                matched = Path(match).resolve(strict=False)
                roots = (Path(root.path) for root in all_rules.file_rules if isinstance(root, FSExposeRule))
                if any(_is_relative_to(matched, root) for root in roots):
                    add(matched, "MASK", "package")
    add(temp, "M", "package")
    return tuple(grants.values())


def network_capabilities(rules: tuple[SocketRule, ...], injected_port: int) -> tuple[str, ...]:
    """Return the broad AppContainer network capabilities required by allowed rules."""
    capabilities: set[str] = set()
    for rule in rules:
        if rule.action != Action.ALLOW or _is_injected_sse_rule(rule, injected_port):
            continue
        network = rule.mask.network
        if network.is_private:
            capabilities.add("privateNetworkClientServer")
        else:
            if Direction.OUT in rule.directions:
                capabilities.add("internetClient")
            if Direction.IN in rule.directions:
                capabilities.add("internetClientServer")
    return tuple(sorted(capabilities))


def has_user_network_rules(rules: tuple[SocketRule, ...], injected_port: int) -> bool:
    """Return whether the profile contains network rules beyond the injected SSE listener rule."""
    return any(not _is_injected_sse_rule(rule, injected_port) for rule in rules)


def has_loopback_network_rule(rules: tuple[SocketRule, ...], injected_port: int) -> bool:
    """Return whether a user allow rule targets only loopback addresses."""
    return any(
        rule.action == Action.ALLOW and not _is_injected_sse_rule(rule, injected_port) and rule.mask.network.is_loopback
        for rule in rules
    )


def has_ignore_in_writable_exposure(rules: tuple[FSExposeRule | IgnoreRule, ...]) -> bool:
    """Return whether an ignore pattern can match future files under a writable exposure."""
    writable_roots = [
        Path(rule.path).resolve(strict=False) for rule in rules if isinstance(rule, FSExposeRule) and rule.write
    ]
    for rule in rules:
        if isinstance(rule, IgnoreRule):
            pattern = Path(rule.source).resolve(strict=False)
            if any(_is_relative_to(pattern, root) for root in writable_roots):
                return True
    return False


def _is_injected_sse_rule(rule: SocketRule, injected_port: int) -> bool:
    return (
        rule.config.path == Path() and rule.config.ln == 0 and rule.config.rule == f"net=ALLOW|TCP|*|{injected_port}|IN"
    )


def _trace(message: str) -> None:
    if sys.platform != "win32":
        return
    with (_mask_journal_path().parent / "acl-trace.log").open("a", encoding="utf-8") as stream:
        stream.write(f"{time.strftime('%H:%M:%S')} pid={os.getpid()} {message}\n")


@contextmanager
def _traced(label: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        _trace(f"{label}: {time.perf_counter() - start:.2f}s")


def apply_acl(path: Path, sid: str, rights: str, *, runtime: bool = False, run_sid: str | None = None) -> None:
    """Add a checked, inheritable filesystem ACE for one SID, tracing its duration."""
    with _traced(f"apply_acl {'runtime' if runtime else 'package'} {rights} {path}"):
        _apply_acl(path, sid, rights, runtime=runtime, run_sid=run_sid)


def _apply_acl(path: Path, sid: str, rights: str, *, runtime: bool = False, run_sid: str | None = None) -> None:
    if not runtime and rights == "RX":
        with _traced(f"  has_broad_read_access {path}"):
            broad = _has_broad_appcontainer_read_access(path)
        if broad:
            return
    mask = _READ_EXECUTE if rights == "RX" else _MODIFY
    try:
        inherit = path.is_dir()
        if run_sid is None:
            with _traced(f"  grant_dacl {path}"):
                _grant_dacl(path, sid, mask, inherit)
        else:
            with _acl_lock():
                runs = _read_run_journal()
                if run_sid not in runs:
                    raise OSError(f"AppContainer run {run_sid} is not registered")
                grants = [] if runtime else runs[run_sid]["grants"]
                path_text = str(path.resolve(strict=False))
                if not runtime and path_text not in grants:
                    grants.append(path_text)
                    _write_run_journal(runs)
                try:
                    with _traced(f"  grant_dacl {path}"):
                        _grant_dacl(path, sid, mask, inherit)
                    if runtime and path.is_dir() and not _runtime_acl_cached(path, sid):
                        _apply_acl_tree(path, sid)
                        _cache_runtime_acl(path, sid)
                except BaseException:
                    if not runtime and path_text in grants:
                        grants.remove(path_text)
                        _write_run_journal(runs)
                    raise
    except OSError as error:
        if runtime:
            command = f'icacls "{path}" /grant *{sid}:(OI)(CI)RX /T'
            raise OSError(
                "Cannot grant AppContainer access to the Python runtime. Run as administrator: " + command
            ) from error
        raise OSError(f"Cannot grant AppContainer access to {path}: {error}") from error


_READ_EXECUTE = 0x1200A9
_MODIFY = 0x1301BF
_ALL_APPLICATION_PACKAGES = ("S-1-15-2-1", "S-1-15-2-2")
_DACL_INFORMATION = 0x00000004
_PROTECTED_DACL = 0x80000000
_UNPROTECTED_DACL = 0x20000000
_SE_DACL_PROTECTED = 0x1000
_SUB_CONTAINERS_AND_OBJECTS_INHERIT = 3
_GRANT_ACCESS = 1
_REVOKE_ACCESS = 4
_ACL_SIZE_INFORMATION = 2
_ACE_SID_OFFSET = 8


class _Trustee(ctypes.Structure):
    _fields_ = [
        ("pMultipleTrustee", ctypes.c_void_p),
        ("MultipleTrusteeOperation", ctypes.c_uint32),
        ("TrusteeForm", ctypes.c_uint32),
        ("TrusteeType", ctypes.c_uint32),
        ("ptstrName", ctypes.c_void_p),
    ]


class _ExplicitAccess(ctypes.Structure):
    _fields_ = [
        ("grfAccessPermissions", ctypes.c_uint32),
        ("grfAccessMode", ctypes.c_uint32),
        ("grfInheritance", ctypes.c_uint32),
        ("Trustee", _Trustee),
    ]


class _AclSizeInformation(ctypes.Structure):
    _fields_ = [("AceCount", ctypes.c_uint32), ("AclBytesInUse", ctypes.c_uint32), ("AclBytesFree", ctypes.c_uint32)]


class _AceHeader(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", ctypes.c_uint16),
        ("Mask", ctypes.c_uint32),
    ]


def _win32_apis() -> tuple[Any, Any]:
    """Return advapi32 and kernel32 with the prototypes of the security functions used here."""
    advapi32 = ctypes.__dict__["WinDLL"]("advapi32", use_last_error=True)
    kernel32 = ctypes.__dict__["WinDLL"]("kernel32", use_last_error=True)
    pointer, dword, out = ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)
    advapi32.ConvertStringSidToSidW.argtypes = (ctypes.c_wchar_p, out)
    advapi32.GetNamedSecurityInfoW.argtypes = (ctypes.c_wchar_p, dword, dword, pointer, pointer, out, pointer, out)
    advapi32.GetNamedSecurityInfoW.restype = dword
    advapi32.GetSecurityDescriptorControl.argtypes = (pointer, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(dword))
    advapi32.SetEntriesInAclW.argtypes = (dword, ctypes.POINTER(_ExplicitAccess), pointer, out)
    advapi32.SetEntriesInAclW.restype = dword
    advapi32.SetNamedSecurityInfoW.argtypes = (ctypes.c_wchar_p, dword, dword, pointer, pointer, pointer, pointer)
    advapi32.SetNamedSecurityInfoW.restype = dword
    advapi32.GetAclInformation.argtypes = (pointer, pointer, dword, dword)
    advapi32.GetAce.argtypes = (pointer, dword, out)
    advapi32.EqualSid.argtypes = (pointer, pointer)
    kernel32.LocalFree.argtypes = (pointer,)
    kernel32.LocalFree.restype = pointer
    return advapi32, kernel32


def _check_status(status: int) -> None:
    if status:
        raise ctypes.__dict__["WinError"](status)


def _check_call(succeeded: int) -> None:
    if not succeeded:
        raise ctypes.__dict__["WinError"](ctypes.__dict__["get_last_error"]())


@contextmanager
def _sid_pointer(sid: str) -> Iterator[ctypes.c_void_p]:
    advapi32, kernel32 = _win32_apis()
    pointer = ctypes.c_void_p()
    _check_call(advapi32.ConvertStringSidToSidW(sid, ctypes.byref(pointer)))
    try:
        yield pointer
    finally:
        kernel32.LocalFree(pointer)


@contextmanager
def _dacl_of(path: Path) -> Iterator[tuple[ctypes.c_void_p, bool]]:
    """Yield a path's DACL and whether it is protected from inheritance, without translating any SID to a name."""
    advapi32, kernel32 = _win32_apis()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    _check_status(
        advapi32.GetNamedSecurityInfoW(
            str(path), 1, _DACL_INFORMATION, None, None, ctypes.byref(dacl), None, ctypes.byref(descriptor)
        )
    )
    try:
        control = ctypes.c_uint16()
        revision = ctypes.c_uint32()
        _check_call(advapi32.GetSecurityDescriptorControl(descriptor, ctypes.byref(control), ctypes.byref(revision)))
        yield dacl, bool(control.value & _SE_DACL_PROTECTED)
    finally:
        kernel32.LocalFree(descriptor)


def _edit_dacl(path: Path, sid: str, mode: int, mask: int, inherit: bool) -> None:
    """Merge one access entry for ``sid`` into a path's DACL, keeping its inheritance protection."""
    advapi32, kernel32 = _win32_apis()
    with _sid_pointer(sid) as sid_pointer, _dacl_of(path) as (dacl, protected):
        access = _ExplicitAccess(
            mask,
            mode,
            _SUB_CONTAINERS_AND_OBJECTS_INHERIT if inherit else 0,
            _Trustee(None, 0, 0, 0, sid_pointer.value),
        )
        merged = ctypes.c_void_p()
        _check_status(advapi32.SetEntriesInAclW(1, ctypes.byref(access), dacl, ctypes.byref(merged)))
        try:
            flag = _PROTECTED_DACL if protected else _UNPROTECTED_DACL
            _check_status(
                advapi32.SetNamedSecurityInfoW(str(path), 1, _DACL_INFORMATION | flag, None, None, merged, None)
            )
        finally:
            kernel32.LocalFree(merged)


def _grant_dacl(path: Path, sid: str, mask: int, inherit: bool) -> None:
    """Add an allow entry for ``sid`` to a path's DACL."""
    _edit_dacl(path, sid, _GRANT_ACCESS, mask, inherit)


def _revoke_dacl(path: Path, sid: str) -> None:
    """Remove every explicit entry of ``sid`` from a path's DACL."""
    _edit_dacl(path, sid, _REVOKE_ACCESS, 0, False)


def _has_allow_ace(path: Path, sids: tuple[str, ...], mask: int) -> bool:
    """Return whether a path's DACL holds an allow entry covering ``mask`` for one of ``sids``."""
    advapi32, _ = _win32_apis()
    with ExitStack() as stack, _dacl_of(path) as (dacl, _):
        if not dacl.value:
            return False
        pointers = [stack.enter_context(_sid_pointer(sid)) for sid in sids]
        size = _AclSizeInformation()
        _check_call(advapi32.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), _ACL_SIZE_INFORMATION))
        for index in range(size.AceCount):
            entry = ctypes.c_void_p()
            _check_call(advapi32.GetAce(dacl, index, ctypes.byref(entry)))
            header = _AceHeader.from_address(entry.value or 0)
            if header.AceType == 0 and header.Mask & mask == mask:
                if any(advapi32.EqualSid((entry.value or 0) + _ACE_SID_OFFSET, pointer) for pointer in pointers):
                    return True
    return False


def _has_broad_appcontainer_read_access(path: Path) -> bool:
    """Return whether Windows already grants read/execute access to all AppContainers."""
    return _has_allow_ace(path, _ALL_APPLICATION_PACKAGES, _READ_EXECUTE)


def mask_acl(path: Path, package_sid: str, runtime_sid: str) -> None:
    """Mask an ignored path and retain its original descriptor until the last run exits."""
    path_key = _mask_path_key(path)
    with _acl_lock():
        journal = _read_mask_journal()
        entry = journal.get(path_key)
        if entry:
            if package_sid not in entry["users"]:
                entry["users"].append(package_sid)
                _write_mask_journal(journal)
                _remove_mask_access(path, package_sid, runtime_sid, protect_inheritance=False)
            return
        sddl = _run_acl_script(
            "([string](Get-Acl -LiteralPath $env:PYSB_PATH).Sddl).Trim()",
            {"PYSB_PATH": str(path)},
            locked=True,
        )
        journal[path_key] = {"sddl": sddl, "users": [package_sid]}
        _write_mask_journal(journal)
        _remove_mask_access(path, package_sid, runtime_sid, protect_inheritance=True)


def _remove_mask_access(path: Path, package_sid: str, runtime_sid: str, *, protect_inheritance: bool) -> None:
    protect = "$acl.SetAccessRuleProtection($true, $true); " if protect_inheritance else ""
    deny_package = (
        "$package = New-Object -TypeName System.Security.Principal.SecurityIdentifier -ArgumentList $env:PYSB_SID; "
        "$deny = New-Object -TypeName System.Security.AccessControl.FileSystemAccessRule -ArgumentList "
        "@($package, [System.Security.AccessControl.FileSystemRights]::FullControl, "
        "[System.Security.AccessControl.AccessControlType]::Deny); $acl.AddAccessRule($deny); "
    )
    sddl = _run_acl_script(
        "$acl = Get-Acl -LiteralPath $env:PYSB_PATH; "
        + protect
        + "$sids = @($env:PYSB_SID, $env:PYSB_RUNTIME_SID, 'S-1-3-4'); "
        "$rules = @($acl.Access | Where-Object { $sids -contains $_.IdentityReference.Value }); "
        "foreach ($rule in $rules) { [void]$acl.RemoveAccessRuleSpecific($rule) }; "
        + deny_package
        + "$acl.GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::Access)",
        {"PYSB_PATH": str(path), "PYSB_SID": package_sid, "PYSB_RUNTIME_SID": runtime_sid},
        locked=True,
    ).strip()
    _set_acl_sddl(path, sddl)


def _run_acl_script(script: str, variables: dict[str, str], *, locked: bool = False) -> str:
    if sys.platform != "win32":
        raise OSError("AppContainer ACL operations are available only on win32")
    script = "$ErrorActionPreference = 'Stop'; " + script
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")

    def run_script() -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, **variables, "ErrorActionPreference": "Stop"},
        )
        return result

    if locked:
        result = run_script()
    else:
        with _acl_lock():
            result = run_script()
    if result.returncode:
        raise OSError(f"AppContainer ACL operation failed for {variables.get('PYSB_PATH')}: {result.stderr.strip()}")
    return result.stdout


def _set_acl_sddl(path: Path, sddl: str) -> None:
    """Set only a path's DACL so ordinary users do not need SACL privileges."""
    from ctypes import wintypes

    advapi32 = ctypes.__dict__["WinDLL"]("advapi32", use_last_error=True)
    kernel32 = ctypes.__dict__["WinDLL"]("kernel32", use_last_error=True)
    descriptor = ctypes.c_void_p()
    convert = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p)
    convert.restype = wintypes.BOOL
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.__dict__["WinError"](ctypes.__dict__["get_last_error"]())
    try:
        present = wintypes.BOOL()
        dacl = ctypes.c_void_p()
        defaulted = wintypes.BOOL()
        get_dacl = advapi32.GetSecurityDescriptorDacl
        get_dacl.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.BOOL),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.BOOL),
        )
        get_dacl.restype = wintypes.BOOL
        if not get_dacl(descriptor, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)):
            raise ctypes.__dict__["WinError"](ctypes.__dict__["get_last_error"]())
        set_named = advapi32.SetNamedSecurityInfoW
        set_named.argtypes = (
            wintypes.LPWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        set_named.restype = wintypes.DWORD
        dacl_information = 0x00000004 | (0x80000000 if "D:P" in sddl else 0x20000000)
        status = set_named(str(path), 1, dacl_information, None, None, dacl if present.value else None, None)
        if status:
            raise ctypes.__dict__["WinError"](status)
    finally:
        kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(descriptor)


def _apply_acl_tree(path: Path, sid: str) -> None:
    """Grant a runtime SID access to existing files beneath an interpreter directory."""
    with _traced(f"icacls inherit {path}"):
        inherit_result = subprocess.run(
            ["icacls.exe", str(path), "/grant", f"*{sid}:(OI)(CI)RX"],
            capture_output=True,
            text=True,
            check=False,
        )
    if inherit_result.returncode:
        details = inherit_result.stderr.strip() or inherit_result.stdout.strip()
        raise OSError(f"Cannot grant AppContainer runtime access to {path}: {details}")
    with _traced(f"icacls recursive {path}"):
        recursive_result = subprocess.run(
            ["icacls.exe", str(path), "/grant", f"*{sid}:RX", "/T"],
            capture_output=True,
            text=True,
            check=False,
        )
    if recursive_result.returncode:
        details = recursive_result.stderr.strip() or recursive_result.stdout.strip()
        raise OSError(f"Cannot grant AppContainer runtime access to {path}: {details}")


def _mask_journal_path() -> Path:
    local_app_data_value = os.environ.get("LOCALAPPDATA")
    if local_app_data_value is None:
        local_app_data_value = str(Path.home() / "AppData" / "Local")
    local_app_data = Path(local_app_data_value)
    state_dir = local_app_data / "pysandboxes" / "appcontainer"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "masks.json"


def _mask_path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _run_journal_path() -> Path:
    return _mask_journal_path().with_name("runs.json")


def _runtime_acl_cache_path() -> Path:
    return _mask_journal_path().with_name("runtime-acls.json")


def _runtime_acl_key(path: Path, sid: str) -> str:
    return f"{os.path.normcase(str(path.resolve(strict=False)))}|{sid}|objects-v2"


def _runtime_acl_cached(path: Path, sid: str) -> bool:
    cache_path = _runtime_acl_cache_path()
    if not cache_path.exists():
        return False
    cached = __import__("json").loads(cache_path.read_text(encoding="utf-8"))
    if not isinstance(cached, list):
        raise OSError(f"Invalid AppContainer runtime ACL cache: {cache_path}")
    return _runtime_acl_key(path, sid) in cached


def _cache_runtime_acl(path: Path, sid: str) -> None:
    import json
    import tempfile

    cache_path = _runtime_acl_cache_path()
    cached = set(json.loads(cache_path.read_text(encoding="utf-8"))) if cache_path.exists() else set()
    cached.add(_runtime_acl_key(path, sid))
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=cache_path.parent, delete=False) as stream:
        json.dump(sorted(cached), stream)
        temporary = Path(stream.name)
    temporary.replace(cache_path)


def begin_run(package_sid: str, profile_name: str) -> Any:
    """Register a run and hold its cross-session lock for its whole lifetime."""
    import msvcrt

    lock_file_path = _mask_journal_path().with_name(f"run-{package_sid}.lock")
    lock_file = lock_file_path.open("a+b")
    lock_file.seek(0, os.SEEK_END)
    if lock_file.tell() == 0:
        lock_file.write(b"\0")
        lock_file.flush()
    _lock_file(lock_file)
    try:
        with _acl_lock():
            for profile in _reap_stale_runs_locked():
                _delete_appcontainer_profile(profile)
            runs = _read_run_journal()
            runs[package_sid] = {
                "profile": profile_name,
                "grants": [],
            }
            _write_run_journal(runs)
    except BaseException:
        msvcrt.__dict__["locking"](lock_file.fileno(), msvcrt.__dict__["LK_UNLCK"], 1)
        lock_file.close()
        raise
    return lock_file


def finish_run(package_sid: str) -> tuple[str, ...]:
    """Remove a run's package grants and masks, returning profiles whose cleanup is complete."""
    with _acl_lock():
        profiles = _finish_run_locked(package_sid)
    return profiles


def mark_window_access(package_sid: str) -> None:
    """Journal a service-session window ACL change before applying it."""
    with _acl_lock():
        runs = _read_run_journal()
        if package_sid not in runs:
            raise OSError(f"AppContainer run {package_sid} is not registered")
        runs[package_sid]["window_access"] = True
        _write_run_journal(runs)


def release_run_lock(lock_file: Any) -> None:
    """Release a run's liveness lock after DACL and profile cleanup."""
    msvcrt = __import__("msvcrt")
    try:
        lock_file.seek(0)
        msvcrt.__dict__["locking"](lock_file.fileno(), msvcrt.__dict__["LK_UNLCK"], 1)
    finally:
        lock_path = Path(lock_file.name)
        lock_file.close()
        lock_path.unlink(missing_ok=True)


def _read_run_journal() -> dict[str, dict[str, Any]]:
    path = _run_journal_path()
    if not path.exists():
        return {}
    data = __import__("json").loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise OSError(f"Invalid AppContainer run journal: {path}")
    return data


def _write_run_journal(runs: dict[str, dict[str, Any]]) -> None:
    import json
    import tempfile

    path = _run_journal_path()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(runs, stream)
        temporary = Path(stream.name)
    temporary.replace(path)


def _reap_stale_runs_locked() -> tuple[str, ...]:
    profiles: list[str] = []
    for package_sid in tuple(_read_run_journal()):
        lock_path = _mask_journal_path().with_name(f"run-{package_sid}.lock")
        with lock_path.open("a+b") as lock_file:
            lock_file.seek(0)
            try:
                __import__("msvcrt").__dict__["locking"](
                    lock_file.fileno(), __import__("msvcrt").__dict__["LK_NBLCK"], 1
                )
            except OSError:
                continue
            try:
                profiles.extend(_finish_run_locked(package_sid))
            finally:
                lock_file.seek(0)
                __import__("msvcrt").__dict__["locking"](
                    lock_file.fileno(), __import__("msvcrt").__dict__["LK_UNLCK"], 1
                )
        lock_path.unlink(missing_ok=True)
    return tuple(profiles)


def _lock_file(lock_file: Any) -> None:
    """Wait until the first byte of a Windows lock file can be locked."""
    msvcrt = __import__("msvcrt")
    lock_file.seek(0)
    started = time.perf_counter()
    while True:
        try:
            msvcrt.__dict__["locking"](lock_file.fileno(), msvcrt.__dict__["LK_NBLCK"], 1)
            _trace(f"  lock acquired after {time.perf_counter() - started:.2f}s")
            return
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EDEADLK):
                raise
            time.sleep(0.05)


def _delete_appcontainer_profile(profile_name: str) -> None:
    userenv = __import__("ctypes").__dict__["WinDLL"]("userenv", use_last_error=True)
    delete = userenv.DeleteAppContainerProfile
    delete.argtypes = (__import__("ctypes").__dict__["c_wchar_p"],)
    delete.restype = __import__("ctypes").__dict__["c_long"]
    result = delete(profile_name)
    if result & 0x80000000:
        if (result & 0xFFFFFFFF) in (0x80070002, 0x80070490):
            return
        raise OSError(f"DeleteAppContainerProfile failed with HRESULT 0x{result & 0xFFFFFFFF:08X}")


def _finish_run_locked(package_sid: str) -> tuple[str, ...]:
    runs = _read_run_journal()
    run = runs.pop(package_sid, None)
    if run is None:
        return ()
    for path in run["grants"]:
        if Path(path).exists():
            _revoke_dacl(Path(path), package_sid)
    if run.get("window_access"):
        from .win_window import remove_service_window_access

        remove_service_window_access(package_sid, locked=True)
    masks = _read_mask_journal()
    for path, entry in tuple(masks.items()):
        if package_sid in entry["users"]:
            entry["users"].remove(package_sid)
            if entry["users"]:
                _write_mask_journal(masks)
            else:
                _restore_mask_locked(Path(path), entry["sddl"])
                del masks[path]
                _write_mask_journal(masks)
    _write_run_journal(runs)
    return (run["profile"],)


def _restore_mask_locked(path: Path, sddl: str) -> None:
    if path.exists():
        _set_acl_sddl(path, sddl)


def _read_mask_journal() -> dict[str, dict[str, Any]]:
    path = _mask_journal_path()
    if not path.exists():
        return {}
    data = __import__("json").loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise OSError(f"Invalid AppContainer ACL journal: {path}")
    return data


def _write_mask_journal(journal: dict[str, dict[str, Any]]) -> None:
    import json
    import tempfile

    path = _mask_journal_path()
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(journal, stream)
        temporary = Path(stream.name)
    temporary.replace(path)


@contextmanager
def _acl_lock() -> Iterator[None]:
    """Serialize DACL read-modify-write operations across processes and sessions."""
    msvcrt = __import__("msvcrt")
    lock = msvcrt.__dict__["locking"]
    unlock_mode = msvcrt.__dict__["LK_UNLCK"]

    with (_mask_journal_path().parent / "acl.lock").open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        _lock_file(lock_file)
        try:
            yield
        finally:
            lock_file.seek(0)
            lock(lock_file.fileno(), unlock_mode, 1)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False
