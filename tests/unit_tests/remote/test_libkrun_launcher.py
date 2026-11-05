# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2

import sys
from pathlib import Path

import pytest

from pysandboxes.remote.libkrun_launcher import (
    ERROR_FILE_NAME,
    MICROVM_FAILED,
    collect_result,
    generate_guest_init_script,
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
