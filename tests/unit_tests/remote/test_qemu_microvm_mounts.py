# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Compaction must preserve effective host paths and 9p permissions."""

from pathlib import Path

import pytest

from pysandboxes.remote import qemu_sse_daemon as daemon


def test_compaction_only_removes_equivalent_children() -> None:
    mounts = [("parent", Path("/host"), "/guest"), ("child", Path("/host/a"), "/guest/a")]
    assert daemon._compact_microvm_mounts(mounts, {"parent", "child"}, "none") == mounts[:1]
    assert daemon._compact_microvm_mounts(mounts, {"parent"}, "none") == mounts
    different_host = [mounts[0], ("child", Path("/elsewhere"), "/guest/a")]
    assert daemon._compact_microvm_mounts(different_host, {"parent", "child"}, "none") == different_host


def test_compaction_preserves_security_models() -> None:
    mounts = [("parent", Path("/etc"), "/etc"), ("child", Path("/etc/ssl"), "/etc/ssl")]
    # The controller allows the readonly /etc parent to use none, including its CA children.
    assert daemon._compact_microvm_mounts(mounts, {"parent", "child"}, "mapped-xattr") == mounts[:1]
    assert daemon._compact_microvm_mounts(mounts, set(), "mapped-xattr") == mounts


def test_compacted_bootstrap_preserves_import_paths() -> None:
    from pysandboxes.remote.qemu_setup import _bootstrap_script_content

    script = _bootstrap_script_content(
        [("parent", "/runtime")], "/run", "3.14", python_paths=["/runtime/venv/lib/site-packages"]
    )
    assert "PYTHONPATH=/runtime/venv/lib/site-packages " in script
    assert "mount -t 9p" in script


def test_bootstrap_requires_guest_native_fallback_paths() -> None:
    from pysandboxes.remote.qemu_setup import _bootstrap_script_content

    script = _bootstrap_script_content(
        [("__pysb_native__", "/etc/ssl")], "/run", "3.14", python_paths=["/runtime/site-packages"]
    )

    assert '[ "$tag" = "__pysb_native__" ]' in script
    assert '[ -e "$path" ] || _pysb_fatal "optional 9p path is absent from the guest image: $path"' in script


def test_microvm_config_uses_readonly_iso_without_config_share(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from types import SimpleNamespace
    from pysandboxes.remote import qemu_setup

    monkeypatch.setattr(daemon, "ensure_image", lambda _: None)
    monkeypatch.setattr(daemon, "_file_rules_mounts", lambda *a, **kw: ([], []))
    monkeypatch.setattr(daemon, "_execution_dirs_mounts", lambda: [("exec", Path("/python/lib"), "/python/lib")])
    commands: list[list[str]] = []
    monkeypatch.setattr(qemu_setup.subprocess, "run", lambda args, **kwargs: commands.append(args))
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.pkl").write_bytes(b"serialized-config")
    rules = SimpleNamespace(os_sandbox_params={}, file_rules=[])
    assets = daemon._prepare_qemu_launch(
        rules, tmp_path, SimpleNamespace(all_rules=rules), tmp_path / "pipe", config_dir=config, microvm=True
    )
    assert assets.mount_specs == []
    assert (tmp_path / "config.pkl").read_bytes() == b"serialized-config"
    assert "config.pkl=config.pkl" in commands[0]
    assert 'CONFIG_PATH="/mnt/cidata/config.pkl"' in (tmp_path / "user-data").read_text()


@pytest.mark.parametrize("source", ["profile", "environment"])
def test_microvm_optional_paths_are_selected_before_cloud_init(
    source: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    mounts = [("project", tmp_path / "project", "/project"), ("ssl", Path("/etc/ssl"), "/etc/ssl")]
    cloud_init_mounts: list[tuple[str, str]] = []
    monkeypatch.setattr(daemon, "ensure_image", lambda _: None)
    monkeypatch.setattr(daemon, "_file_rules_mounts", lambda *args, **kwargs: (mounts, [(a, c) for a, _, c in mounts]))
    monkeypatch.setattr(daemon, "_qemu_binary", lambda: "qemu")
    monkeypatch.setattr(daemon, "qemu_accel_args", lambda _: [])
    monkeypatch.setattr(daemon, "microvm_mmio_capacity", lambda *_: 3)
    monkeypatch.setattr(
        daemon,
        "prepare_guest_env",
        lambda *args, **kwargs: cloud_init_mounts.extend(kwargs["mounts"]) or tmp_path / "seed.iso",
    )
    params = {"microvm_optional_paths": "/etc/ssl"} if source == "profile" else {}
    if source == "environment":
        monkeypatch.setenv("QEMU_MICROVM_OPTIONAL_PATHS", "/etc/ssl,/etc/pki")
    rules = SimpleNamespace(os_sandbox_params=params, file_rules=[])

    assets = daemon._prepare_qemu_launch(
        rules, tmp_path, SimpleNamespace(all_rules=rules), tmp_path / "pipe", microvm=True
    )

    assert assets.mount_specs == [mounts[0]]
    assert cloud_init_mounts == [("project", "/project"), ("__pysb_native__", "/etc/ssl")]


def test_execution_mount_is_readonly_but_explicit_write_grant_is_not(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from pysandboxes.guard_files import FSExposeRule
    from pysandboxes.sb_types import ConfigLine

    rules = SimpleNamespace(
        os_sandbox_params={},
        file_rules=[FSExposeRule("/app/tmp", True, ConfigLine("expose-rw=/app/tmp", Path("profile"), 1))],
    )
    mounts = [("pysb_exec_0", Path("/app"), "/app"), ("pysb_0", Path("/app/tmp"), "/app/tmp")]
    readonly = daemon._microvm_readonly_tags(rules, mounts)
    assert readonly == {"pysb_exec_0"}
    assert daemon._compact_microvm_mounts(mounts, readonly, "mapped-xattr") == mounts


def test_microvm_halts_via_reboot_exit_without_acpi() -> None:
    from pysandboxes.remote.qemu_setup import _bootstrap_script_content

    script = _bootstrap_script_content([], "/run", "3.14", config_guest_path="/mnt/cidata/config.pkl")
    assert script.index("sync 2>/dev/null") < script.index("echo b > /proc/sysrq-trigger")
    assert "echo o > /proc/sysrq-trigger" not in script


def test_shared_profile_fits_exactly_eight_transports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import socket
    import sys
    from pysandboxes import guard_socket
    from pysandboxes.python_sb import _load_rules

    project = Path(__file__).resolve().parents[3]
    monkeypatch.chdir(project)
    for key, value in {
        "OS_SANDBOX": "qemu-microvm",
        "TERM": "dumb",
        "My_ENV": "1",
        "PYTHON_BASE_PREFIX": sys.base_prefix,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        guard_socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
    )
    monkeypatch.setattr(daemon, "_virtfs_stage_exec_needed", lambda _: False)
    rules = _load_rules(project / "tests/integration_tests/py-sandbox-test.profile", {})
    mounts, _ = daemon._file_rules_mounts(rules, tmp_path, tmp_path / "pipe", microvm=True)
    assert len(mounts) + 2 == 8, mounts
    readonly = daemon._microvm_readonly_tags(rules, mounts)
    assert any(host == project / "tmp" and tag not in readonly for tag, host, _ in mounts)
    assert all(tag != "pysb_config" for tag, _, _ in mounts)


def test_native_file_contract_uses_eight_transports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from types import SimpleNamespace
    from pysandboxes.python_sb import _load_rules
    from tests.integration_tests import test_os_file_confinement as files

    host_secret = tmp_path / "host-secret"
    host_secret.write_text("host secret")
    with monkeypatch.context() as launch:
        launch.setattr(
            files.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="{}", stderr="")
        )
        files._run(tmp_path, host_secret, "qemu-microvm", "python-sb")
    rules = _load_rules(tmp_path / "files.profile", {})
    mounts, _ = daemon._file_rules_mounts(rules, tmp_path, tmp_path / "pipe", microvm=True)
    assert len(mounts) + 2 == 8, mounts


def test_guard_fixture_fits_eight_transports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from types import SimpleNamespace
    from pysandboxes.python_sb import _load_rules
    from tests.integration_tests import test_guards_with_providers as guards

    with monkeypatch.context() as launch:
        launch.setattr(
            guards.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr="")
        )
        guards._run("qemu-microvm", "python-import=*\n", "print('probe')", tmp_path)
    rules = _load_rules(tmp_path / "guard.profile", {})
    mounts, _ = daemon._file_rules_mounts(rules, tmp_path, tmp_path / "pipe", microvm=True)
    assert len(mounts) + 2 == 8, mounts


def test_runtime_paths_preserve_most_specific_explicit_write_grant() -> None:
    from types import SimpleNamespace
    from pysandboxes.guard_files import FSExposeRule
    from pysandboxes.sb_types import ConfigLine

    config = ConfigLine("expose-rw=/app", Path("profile"), 1)
    rules = SimpleNamespace(file_rules=[FSExposeRule("/app", True, config)])
    mounts = [("pysb_0", Path("/app"), "/app"), ("pysb_exec_0", Path("/app/lib"), "/app/lib")]
    readonly = daemon._microvm_readonly_tags(rules, mounts)
    assert "pysb_exec_0" not in readonly
    assert daemon._compact_microvm_mounts(mounts, readonly, "mapped-xattr") == mounts[:1]
    rules.file_rules.append(FSExposeRule("/app/lib", False, config))
    assert "pysb_exec_0" in daemon._microvm_readonly_tags(rules, mounts)


def test_equal_depth_explicit_modes_follow_mount_order() -> None:
    from types import SimpleNamespace
    from pysandboxes.guard_files import FSExposeRule
    from pysandboxes.sb_types import ConfigLine

    config = ConfigLine("expose-rw=/app", Path("profile"), 1)
    rw, ro = FSExposeRule("/app", True, config), FSExposeRule("/app", False, config)
    mounts = [("pysb_exec_0", Path("/app/lib"), "/app/lib")]
    assert "pysb_exec_0" in daemon._microvm_readonly_tags(SimpleNamespace(file_rules=[rw, ro]), mounts)
    assert "pysb_exec_0" not in daemon._microvm_readonly_tags(SimpleNamespace(file_rules=[ro, rw]), mounts)


def test_microvm_prepares_guest_only_cwd_with_safe_shell_quoting(tmp_path: Path) -> None:
    import subprocess
    from pysandboxes.remote.qemu_setup import _bootstrap_script_content

    cwd = tmp_path / "hidden '$(touch injected) directory"
    script = _bootstrap_script_content(
        [], "/run", "3.14", config_guest_path="/mnt/cidata/config.pkl", guest_cwd=str(cwd)
    )
    commands = [line for line in script.splitlines() if line.startswith(("mkdir -p --", "cd --"))]
    done = subprocess.run(
        ["bash", "-c", "\n".join(commands) + '\nprintf "%s" "$PWD"'],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert done.stdout == str(cwd)
    assert cwd.is_dir()
    assert not (tmp_path / "injected").exists()


def test_hidden_microvm_cwd_keeps_explicit_pythonpath_without_implicit_import(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import os
    from unittest.mock import Mock
    from tests.integration_tests import test_guards_with_providers as guards

    hidden = tmp_path / "hidden"
    hidden.mkdir()
    launch = Mock()
    monkeypatch.setattr(guards.subprocess, "run", launch)
    guards._run("qemu-microvm", "python-import=*\n", "print('probe')", tmp_path, cwd=hidden)
    assert launch.call_args.args[0][1] == "-P"
    assert str(guards.ROOT_DIR) in launch.call_args.kwargs["env"]["PYTHONPATH"].split(os.pathsep)
