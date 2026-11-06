# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""What the QEMU daemon prepares on the host before it launches the VM, observed without booting one."""

import asyncio
import os
import pickle
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.guard_files import FSExposeRule
from pysandboxes.remote import client_subprocess_sse_daemon as client
from pysandboxes.remote import qemu_sse_daemon as q
from pysandboxes.remote.daemon_parameters import DaemonParameters
from pysandboxes.remote.qemu_sse_daemon import QemuSSEDaemon
from pysandboxes.sb_types import ConfigLine, Envs


@pytest.mark.parametrize("accel", [[], ["-enable-kvm"]])
def test_pc_command_preserves_disks_devices_and_mount_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, accel: list[str]
) -> None:
    image = tmp_path / "cloudimg.img"
    iso = tmp_path / "nocloud.iso"
    readonly = tmp_path / "readonly"
    writable = tmp_path / "writable"
    config = ConfigLine("expose", Path("profile"), 1)
    rules = EmptyRules._replace(
        os_sandbox_params={"memory": "1024"},  # type: ignore[arg-type]
        file_rules=(FSExposeRule(str(readonly), False, config), FSExposeRule(str(writable), True, config)),
    )
    monkeypatch.setattr(q, "get_default_image_path", lambda: image)
    monkeypatch.setattr(q, "ensure_image", lambda path: None)
    monkeypatch.setattr(q, "prepare_guest_env", lambda *args, **kwargs: iso)
    monkeypatch.setattr(q, "qemu_accel_args", lambda params: accel)
    monkeypatch.setattr(q, "_qemu_binary", lambda: "qemu-system-x86_64")
    monkeypatch.setattr(q, "_virtfs_security_model", lambda path, model: model)
    monkeypatch.setattr(
        q,
        "_file_rules_mounts",
        lambda *args, **kwargs: ([("pysb_0", readonly, "/ro"), ("pysb_1", writable, "/rw")], []),
    )

    process_config = DaemonParameters(rules, 20, "", False, "token", 4242, "")
    cmd, env = QemuSSEDaemon("token")._build_qemu_cmd(rules, tmp_path, process_config, 4242, tmp_path / "pipe")

    assert (cmd, env) == (
        [
            "qemu-system-x86_64",
            *accel,
            "-m",
            "1024",
            "-snapshot",
            "-drive",
            f"file={image},format=qcow2,if=virtio",
            "-drive",
            f"file={iso},format=raw,if=virtio",
            "-display",
            "none",
            "-monitor",
            "none",
            "-serial",
            "stdio",
            "-nic",
            "user,hostfwd=tcp:127.0.0.1:4242-:4242,model=virtio-net-pci",
            "-virtfs",
            f"local,path={readonly},id=pysb_0,security_model=mapped-xattr,mount_tag=pysb_0,readonly=on",
            "-virtfs",
            f"local,path={writable},id=pysb_1,security_model=mapped-xattr,mount_tag=pysb_1",
            "-device",
            "virtio-serial-pci",
            "-device",
            "virtserialport,name=org.qemu.guest_agent.0",
        ],
        {},
    )


class _Launched(Exception):
    pass


class _Run:
    def __init__(self, daemon: QemuSSEDaemon) -> None:
        self.daemon = daemon
        self.build: dict[str, Any] = {}
        self.launch: dict[str, Any] = {}


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    daemon = QemuSSEDaemon("token")
    state = _Run(daemon)

    def build(self: Any, all_rules: Any, temp: Path, process_config: Any, port: int, pipe: Path, **kwargs: Any) -> Any:
        state.build = {"process_config": process_config, **kwargs}
        return ["qemu"], None

    async def launch(**kwargs: Any) -> Any:
        state.launch = kwargs
        raise _Launched

    monkeypatch.setattr(QemuSSEDaemon, "_build_qemu_cmd", build)
    monkeypatch.setattr(q, "launch_sandbox", launch)
    monkeypatch.chdir(tmp_path)

    def start(all_rules: AllRules, *, init_fn: Any = None) -> _Run:
        pipe = tmp_path / "run" / "pipe"
        pipe.parent.mkdir(exist_ok=True)
        daemon._accept_incoming = True
        with pytest.raises(_Launched):
            asyncio.run(daemon._re_start_cmd(all_rules, [], {"EXTRA": "1"}, pipe, 4242, log_level=20, init_fn=init_fn))
        daemon._remove_stage_root()
        return state

    return start


def test_the_daemon_stops_accepting_calls_while_it_restarts(run: Any) -> None:
    assert run(EmptyRules).daemon._accept_incoming is False


@pytest.mark.parametrize(("init_fn", "reference"), [(print, "mod:fn"), (None, "")])
def test_the_init_function_travels_as_a_reference(
    run: Any, monkeypatch: pytest.MonkeyPatch, init_fn: Any, reference: str
) -> None:
    monkeypatch.setattr(client, "get_callable_info", lambda func: ("mod", "fn"))
    state = run(EmptyRules, init_fn=init_fn)

    sent = pickle.loads((state.build["config_dir"] / "config.pkl").read_bytes())
    assert sent.init_fn == reference


def test_the_guest_gets_only_the_rule_environment_unless_learning(
    run: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PYSB_PROBE_ONLY_IN_HOST", "1")
    rules = EmptyRules._replace(envs=Envs({"RULE": "1"}))

    env = dict(run(rules).launch["envs"])

    assert env == {"RULE": "1", "EXTRA": "1", "TMPDIR": str(tmp_path / "run")}


def test_learning_starts_from_the_host_environment(run: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYSB_PROBE_ONLY_IN_HOST", "1")
    rules = EmptyRules._replace(learn=True, envs=Envs({"RULE": "1"}))

    env = dict(run(rules).launch["envs"])

    assert env["PYSB_PROBE_ONLY_IN_HOST"] == "1"
    assert env["RULE"] == "1"
    assert env["PATH"] == os.environ["PATH"]


@pytest.mark.parametrize("debug", [False, True])
def test_the_config_is_staged_in_the_run_dir_unless_debugging(
    run: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, debug: bool
) -> None:
    monkeypatch.setattr(q, "DEBUG_CONFIG", debug)

    config_dir = run(EmptyRules).build["config_dir"]

    assert config_dir == (Path("tmp") if debug else tmp_path / "run") / "pysb_config"


@pytest.mark.parametrize(("show", "stream"), [(False, subprocess.DEVNULL), (True, subprocess.PIPE)])
def test_the_console_streams_follow_the_boot_console_knob(run: Any, show: bool, stream: int) -> None:
    rules = EmptyRules._replace(os_sandbox_params={"show_boot_console": "true"} if show else {})  # type: ignore[arg-type]

    launch = run(rules).launch

    assert (launch["stdout"], launch["stderr"]) == (stream, stream)
    assert launch["stdin"] == subprocess.DEVNULL
