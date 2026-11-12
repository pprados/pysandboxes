# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2

import resource
import sys
from pathlib import Path
from typing import Any

import pytest

from pysandboxes.remote.libkrun_launcher import (
    ERROR_FILE_NAME,
    MICROVM_FAILED,
    collect_result,
    generate_guest_init_script,
    raise_open_files_limit,
)

_NET = {"address": "10.0.2.200", "prefix": "24", "gateway": "10.0.2.254", "dns": "10.0.2.3"}


def test_the_guest_command_runs_in_a_clean_environment() -> None:
    script = generate_guest_init_script("/run", ["/usr/bin/python3", "-m", "x"], [], {"A": "b c"})

    assert "env -i A='b c' /usr/bin/python3 -m x" in script


def test_a_vsock_port_starts_the_command_behind_the_listener_shim() -> None:
    script = generate_guest_init_script("/run", ["/usr/bin/python3", "-m", "x"], [], {}, vsock_port=4242)

    assert "/tmp/pysb_run/vsock_listen.py 4242 -- /usr/bin/python3 -m x" in script


def test_a_network_configures_the_guest_interface_and_resolver() -> None:
    script = generate_guest_init_script("/run", ["/bin/true"], [], {}, net=_NET)

    assert "ip addr add 10.0.2.200/24 dev eth0" in script
    assert "ip route add default via 10.0.2.254" in script
    assert "nameserver 10.0.2.3" in script


def test_without_a_network_the_guest_has_only_loopback() -> None:
    script = generate_guest_init_script("/run", ["/bin/true"], [], {})

    assert "eth0" not in script and "ip link set lo up" in script


def test_the_exit_code_of_the_guest_is_reported(tmp_path: Path) -> None:
    (tmp_path / "exitcode").write_text("3")

    assert collect_result(str(tmp_path)) == 3


def test_a_micro_vm_that_ends_silently_is_a_failure_not_a_success(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ERROR_FILE_NAME).write_text("Traceback: boom")

    assert collect_result(str(tmp_path)) == MICROVM_FAILED
    assert "boom" in capsys.readouterr().err


def test_the_captured_output_of_the_guest_is_replayed(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "guest.out").write_text("out-text")
    (tmp_path / "guest.err").write_text("err-text")
    (tmp_path / "exitcode").write_text("0")

    assert collect_result(str(tmp_path)) == 0
    captured = capfd.readouterr()
    assert "out-text" in captured.out and "err-text" in captured.err


def test_the_launcher_refuses_a_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from pysandboxes.remote import libkrun_launcher

    monkeypatch.setattr(sys, "argv", ["libkrun_launcher"])
    with pytest.raises(SystemExit, match="usage"):
        libkrun_launcher.main()


def _script(**kwargs: Any) -> str:
    return generate_guest_init_script("/run", ["/usr/bin/python3", "-m", "x"], [], {}, **kwargs)


def test_the_new_root_is_built_and_entered_before_the_command_runs() -> None:
    script = _script(ro_paths=["/usr"])

    assert script.index("mount --bind /usr /proc/usr") < script.index("pivot_root") < script.index("setpriv")


def test_a_failure_to_build_the_root_stops_the_micro_vm() -> None:
    script = _script(ro_paths=["/usr"])

    assert "pivot_root . oldroot || fail" in script
    assert "|| fail 'cannot expose /usr'" in script
    assert "fail() {" in script and "reboot -f" in script


def test_the_command_runs_without_privilege() -> None:
    script = _script(uid=1234, gid=5678)

    for option in ("--reuid=1234", "--regid=5678", "--clear-groups", "--bounding-set=-all", "--no-new-privs"):
        assert option in script


def test_the_old_root_is_detached_and_the_new_one_is_read_only() -> None:
    script = _script()

    assert script.index("umount -l /oldroot") < script.index("mount -o remount,ro /")


def test_a_read_only_bind_is_remounted_read_only() -> None:
    assert "mount -o remount,bind,ro /proc/usr" in _script(ro_paths=["/usr"])


def test_a_writable_share_is_mounted_in_the_new_root_before_the_switch() -> None:
    script = generate_guest_init_script(
        "/run", ["/bin/true"], [{"tag": "fs_0", "guest_path": "/work", "readonly": False}], {}
    )

    assert script.index("mount -t virtiofs fs_0 /proc/work") < script.index("pivot_root")


def test_a_masked_directory_and_file_are_hidden_before_the_switch() -> None:
    script = _script(masks=[("/work/dir", True), ("/work/file", False)])

    assert "mount -t tmpfs -o ro tmpfs /proc/work/dir" in script
    assert "mount --bind /proc/dev/null /proc/work/file" in script
    assert script.index("/proc/work/file") < script.index("pivot_root")


def test_a_path_under_an_exposed_directory_is_not_bound_again() -> None:
    script = _script(ro_paths=["/usr", "/usr/bin/python3"])

    assert "mount --bind /usr /proc/usr" in script
    assert "/proc/usr/bin/python3" not in script


def test_the_open_files_soft_limit_is_lifted_to_the_hard_one(monkeypatch: pytest.MonkeyPatch) -> None:
    limits: list[tuple[int, int]] = []
    monkeypatch.setattr(resource, "getrlimit", lambda _: (1024, 524288))
    monkeypatch.setattr(resource, "setrlimit", lambda _, value: limits.append(value))

    raise_open_files_limit()

    assert limits == [(524288, 524288)]


def test_the_open_files_limit_is_left_alone_when_already_at_the_hard_one(monkeypatch: pytest.MonkeyPatch) -> None:
    limits: list[tuple[int, int]] = []
    monkeypatch.setattr(resource, "getrlimit", lambda _: (4096, 4096))
    monkeypatch.setattr(resource, "setrlimit", lambda _, value: limits.append(value))

    raise_open_files_limit()

    assert limits == []


def test_the_host_directories_no_rule_names_are_never_mounted() -> None:
    assert "/home" not in _script(ro_paths=["/usr", "/etc"])
