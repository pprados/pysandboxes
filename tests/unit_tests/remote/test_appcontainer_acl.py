# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Tests for AppContainer ACL rule planning."""

from ipaddress import ip_network
import builtins
import errno
from pathlib import Path
from contextlib import nullcontext
from tempfile import TemporaryFile
from types import SimpleNamespace

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.remote import appcontainer_acl
from pysandboxes.remote.appcontainer_acl import (
    build_acl_plan,
    has_ignore_in_writable_exposure,
    has_user_network_rules,
    network_capabilities,
)
from pysandboxes.sb_types import ConfigLine


def test_build_acl_plan_maps_exposed_paths_and_existing_ignores(tmp_path: Path) -> None:
    root = tmp_path / "root"
    hidden = root / "hidden.txt"
    root.mkdir()
    hidden.write_text("hidden")
    rules = EmptyRules._replace(
        file_rules=(
            FSExposeRule(str(root), False, ConfigLine("expose-ro=", tmp_path, 1)),
            IgnoreRule(str(hidden), ConfigLine("ignore=", tmp_path, 2)),
        )
    )

    plan = build_acl_plan(rules, tmp_path / "temp")

    assert next(grant for grant in plan if grant.path == root).rights == "RX"
    assert next(grant for grant in plan if grant.path == hidden).rights == "MASK"


def test_network_capabilities_omit_only_injected_inbound_sse_rule() -> None:
    rule = SocketRule(
        Action.ALLOW,
        SocketMask((Kind.TCP,), ip_network("0.0.0.0/0"), (43210,)),
        (Direction.IN,),
        ConfigLine("net=ALLOW|TCP|*|43210|IN", Path(), 0),
    )
    outbound = rule._replace(directions=(Direction.OUT,), config=ConfigLine("net=ALLOW|TCP|*|43210|OUT", Path(), 1))

    assert network_capabilities((rule,), 43210) == ()
    assert network_capabilities((outbound,), 43210) == ("internetClient",)
    assert not has_user_network_rules((rule,), 43210)
    assert has_user_network_rules((outbound,), 43210)
    inbound = outbound._replace(directions=(Direction.IN,), config=ConfigLine("net=ALLOW|TCP|*|43210|IN", Path(), 1))
    assert network_capabilities((inbound,), 43210) == ("internetClientServer",)


def test_ignore_under_writable_exposure_is_reported(tmp_path: Path) -> None:
    root = tmp_path / "writable"
    rules = (
        FSExposeRule(str(root), True, ConfigLine("expose-rw=", tmp_path, 1)),
        IgnoreRule(str(root / "*.secret"), ConfigLine("ignore=", tmp_path, 2)),
    )

    assert has_ignore_in_writable_exposure(rules)


def test_ignore_mask_is_kept_until_its_last_run_exits(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(appcontainer_acl, "_acl_lock", nullcontext)
    calls: list[str] = []

    def run_script(script: str, variables: dict[str, str], *, locked: bool = False) -> str:
        calls.append(script)
        return "original-sddl" if ").Sddl" in script or "GetSecurityDescriptorSddlForm" in script else ""

    monkeypatch.setattr(appcontainer_acl, "_run_acl_script", run_script)
    set_calls: list[tuple[Path, str]] = []
    monkeypatch.setattr(appcontainer_acl, "_set_acl_sddl", lambda path, sddl: set_calls.append((path, sddl)))
    path = tmp_path / "exposed" / "secret.txt"
    path.parent.mkdir()
    path.touch()
    appcontainer_acl.mask_acl(path, "package-1", "runtime")
    appcontainer_acl._write_run_journal(
        {"package-1": {"profile": "profile-1", "grants": []}, "package-2": {"profile": "profile-2", "grants": []}}
    )
    appcontainer_acl.mask_acl(path, "package-2", "runtime")

    appcontainer_acl.finish_run("package-1")
    mask_journal = appcontainer_acl._read_mask_journal()
    assert mask_journal[appcontainer_acl._mask_path_key(path)]["users"] == ["package-2"]
    assert len(calls) == 3

    appcontainer_acl.finish_run("package-2")
    assert appcontainer_acl._read_mask_journal() == {}
    assert len(calls) == 3
    assert set_calls[-1] == (path, "original-sddl")


def test_finish_run_removes_its_package_sid_grants(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(appcontainer_acl, "_acl_lock", nullcontext)
    path = tmp_path / "exposed"
    appcontainer_acl._write_run_journal(
        {"package": {"profile": "profile", "grants": [str(path)], "window_access": False}}
    )
    calls: list[tuple[str, dict[str, str]]] = []

    def run_script(script: str, variables: dict[str, str], *, locked: bool = False) -> str:
        calls.append((script, variables))
        return ""

    monkeypatch.setattr(appcontainer_acl, "_run_acl_script", run_script)

    assert appcontainer_acl.finish_run("package") == ("profile",)
    assert calls[0][1] == {"PYSB_PATH": str(path), "PYSB_SID": "package"}
    assert appcontainer_acl._read_run_journal() == {}


def test_runtime_acl_cache_is_scoped_to_path_and_capability(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    path = tmp_path / "python"

    assert not appcontainer_acl._runtime_acl_cached(path, "runtime-a")
    appcontainer_acl._cache_runtime_acl(path, "runtime-a")

    assert appcontainer_acl._runtime_acl_cached(path, "runtime-a")
    assert not appcontainer_acl._runtime_acl_cached(path, "runtime-b")


def test_read_only_grant_reuses_windows_appcontainer_access(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "system"
    monkeypatch.setattr(appcontainer_acl, "_has_broad_appcontainer_read_access", lambda target: True)

    def fail_if_acl_is_changed(target: Path, sddl: str) -> None:
        raise AssertionError("Existing AppContainer read access should be reused")

    monkeypatch.setattr(appcontainer_acl, "_set_acl_sddl", fail_if_acl_is_changed)

    appcontainer_acl.apply_acl(path, "package", "RX")


def test_runtime_acl_tree_grants_existing_objects_and_inheritance(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(appcontainer_acl.subprocess, "run", run)
    appcontainer_acl._apply_acl_tree(tmp_path, "runtime")

    assert calls == [
        ["icacls.exe", str(tmp_path), "/grant", "*runtime:(OI)(CI)RX"],
        ["icacls.exe", str(tmp_path), "/grant", "*runtime:RX", "/T"],
    ]


def test_file_acl_grant_omits_inheritance_flags(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "config.bin"
    path.touch()
    script_variables: dict[str, str] = {}
    monkeypatch.setattr(appcontainer_acl, "_has_broad_appcontainer_read_access", lambda target: False)

    def run_script(script: str, variables: dict[str, str], *, locked: bool = False) -> str:
        script_variables.update(variables)
        assert "if ($env:PYSB_IS_DIR -eq 'true')" in script
        return "descriptor"

    monkeypatch.setattr(appcontainer_acl, "_run_acl_script", run_script)
    monkeypatch.setattr(appcontainer_acl, "_set_acl_sddl", lambda target, sddl: None)

    appcontainer_acl.apply_acl(path, "package", "M")

    assert script_variables["PYSB_IS_DIR"] == "false"


def test_lock_file_waits_through_contention(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    real_import = builtins.__import__
    attempts = 0
    sleeps: list[float] = []

    def locking(*args: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError(errno.EDEADLK, "lock held")

    monkeypatch.setattr(
        builtins,
        "__import__",
        lambda name, *args, **kwargs: (
            SimpleNamespace(LK_NBLCK=1, locking=locking) if name == "msvcrt" else real_import(name, *args, **kwargs)
        ),
    )
    monkeypatch.setattr(appcontainer_acl.time, "sleep", sleeps.append)

    with TemporaryFile() as lock_file:
        appcontainer_acl._lock_file(lock_file)

    assert attempts == 2
    assert sleeps == [0.05]
