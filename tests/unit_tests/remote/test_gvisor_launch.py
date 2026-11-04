# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""The launcher runs on the host, in the private network namespace, before any sandboxed code exists.

It must hold the guest back until the network is filtered, and never start it when the filter does not load.
"""

import json
import os
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from pysandboxes.all_rules import AllRules, EmptyRules
from pysandboxes.guard_socket import SocketRules
from pysandboxes.guard_socket import parse_rules as parse_socket_rules
from pysandboxes.remote.gvisor_launch import launcher_script, netfilter_rules
from pysandboxes.sb_types import ConfigLine


def _rules(*lines: str) -> AllRules:
    parsed, *_ = parse_socket_rules([ConfigLine(line, Path("profile"), 1) for line in lines], [])
    return EmptyRules._replace(socket_rules=SocketRules(list(parsed)))


class TestNetfilterRules:
    def test_everything_is_dropped_without_a_rule(self) -> None:
        rules = netfilter_rules(EmptyRules, port=4242)

        assert ":INPUT DROP [0:0]" in rules
        assert ":OUTPUT DROP [0:0]" in rules
        assert rules[-1] == "COMMIT"

    def test_the_daemon_port_is_open_to_the_forwarder_only(self) -> None:
        rules = netfilter_rules(EmptyRules, port=4242)

        accepted = [r for r in rules if "4242" in r]
        assert len(accepted) == 1
        assert "-s 10.0.2.2/32" in accepted[0]
        assert accepted[0].startswith("-A INPUT") and accepted[0].endswith("-j ACCEPT")

    def test_the_resolver_of_the_forwarder_is_the_only_dns_allowed(self) -> None:
        rules = netfilter_rules(EmptyRules, port=4242)

        dns = [r for r in rules if "--dport 53" in r]
        assert len(dns) == 1
        assert "-d 10.0.2.3/32" in dns[0]

    def test_an_allowed_destination_is_opened(self) -> None:
        rules = netfilter_rules(_rules("net=ALLOW|TCP|1.1.1.1|80|OUT"), port=4242)

        assert any("-d 1.1.1.1/32" in r and "--dports 80" in r and r.endswith("ACCEPT") for r in rules)

    def test_a_destination_without_a_rule_stays_closed(self) -> None:
        rules = netfilter_rules(_rules("net=ALLOW|TCP|1.1.1.1|80|OUT"), port=4242)

        assert not any("1.0.0.1" in r for r in rules)


class _Launcher:
    """The script run against fake tools, which record what they were asked to do."""

    def __init__(self, tmp_path: Path, *, restore_exit: int = 0) -> None:
        self.dir = tmp_path
        self.log = tmp_path / "log"
        self.ready = tmp_path / "ready"
        self.fifo = tmp_path / "fifo"
        self.config = tmp_path / "config"
        self.rules = tmp_path / "rules"
        self.rules.write_text("*filter\nCOMMIT\n")
        self.spec = tmp_path / "config.json"
        self.spec.write_text(json.dumps({"process": {"args": ["python", "-m", "main_sandbox"]}}))
        os.mkfifo(self.fifo)
        self.ip = self._tool("ip", "echo ip $@ >> LOG")
        self.restore = self._tool("iptables-restore", f"echo restore $(cat) >> LOG; exit {restore_exit}")
        self.runsc = self._tool("runsc", 'echo "runsc $@ config=$(cat CONFIG)" >> LOG')

    def _tool(self, name: str, body: str) -> Path:
        path = self.dir / name
        body = body.replace("LOG", shlex.quote(str(self.log))).replace("CONFIG", shlex.quote(str(self.config)))
        path.write_text("#!/bin/sh\n" + body + "\n")
        path.chmod(0o755)
        return path

    def script(self) -> str:
        return launcher_script(
            ready_file=str(self.ready),
            config_fifo=str(self.fifo),
            config_copy=str(self.config),
            rules_file=str(self.rules),
            spec_file=str(self.spec),
            python=sys.executable,
            ip=str(self.ip),
            iptables_restore=str(self.restore),
            runsc_argv=[str(self.runsc), "run", "--bundle", "/b"],
        )

    def guest_args(self) -> list[str]:
        return json.loads(self.spec.read_text())["process"]["args"]

    def start(self, *user_args: str, stdin: int | None = None) -> subprocess.Popen[bytes]:
        # What python-sb and launch_sandbox append to every command line: the user's arguments, then the pipe.
        return subprocess.Popen(
            ["sh", "-c", self.script(), "gvisor-launcher", *user_args, "--_named-pipe", str(self.fifo)],
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def feed(self, payload: bytes) -> threading.Thread:
        def write() -> None:
            with open(self.fifo, "wb") as fifo:
                fifo.write(payload)

        thread = threading.Thread(target=write, daemon=True)
        thread.start()
        return thread

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []


class TestLauncherScript:
    def test_nothing_runs_until_the_network_is_ready(self, tmp_path: Path) -> None:
        launcher = _Launcher(tmp_path)
        process = launcher.start()

        time.sleep(0.4)

        assert launcher.calls() == [], "the guest and the filter wait for slirp4netns"
        launcher.ready.touch()
        launcher.feed(b"PAYLOAD")
        assert process.wait(timeout=10) == 0

    def test_the_guest_reads_a_blocking_stdin_even_when_the_host_one_is_not(self, tmp_path: Path) -> None:
        # runsc copies the non-blocking flag of the host stdin to the guest, whose reads then fail with EAGAIN.
        launcher = _Launcher(tmp_path)
        launcher.runsc.write_text(
            f"#!/bin/sh\n{shlex.quote(sys.executable)} -c "
            f"\"import os; open({str(launcher.log)!r}, 'w').write(str(os.get_blocking(0)))\"\n"
        )
        read_end, write_end = os.pipe()
        os.set_blocking(read_end, False)
        launcher.ready.touch()
        launcher.feed(b"PAYLOAD")

        assert launcher.start(stdin=read_end).wait(timeout=10) == 0

        os.close(read_end)
        os.close(write_end)
        assert launcher.calls() == ["True"]

    def test_the_filter_is_loaded_before_the_guest_starts(self, tmp_path: Path) -> None:
        launcher = _Launcher(tmp_path)
        launcher.ready.touch()
        launcher.feed(b"PAYLOAD")

        assert launcher.start().wait(timeout=10) == 0

        order = [call.split()[0] for call in launcher.calls()]
        assert order == ["ip", "restore", "runsc"]
        assert "*filter" in launcher.calls()[1]

    def test_the_guest_never_starts_when_the_filter_does_not_load(self, tmp_path: Path) -> None:
        launcher = _Launcher(tmp_path, restore_exit=1)
        launcher.ready.touch()
        launcher.feed(b"PAYLOAD")

        assert launcher.start().wait(timeout=10) != 0

        assert not any(call.startswith("runsc") for call in launcher.calls())

    def test_the_config_is_relayed_from_the_fifo_to_a_file_the_guest_can_open(self, tmp_path: Path) -> None:
        launcher = _Launcher(tmp_path)
        launcher.ready.touch()
        launcher.feed(b"PAYLOAD")

        assert launcher.start().wait(timeout=10) == 0

        assert launcher.calls()[-1].endswith("config=PAYLOAD"), "the guest cannot open a host FIFO"

    def test_the_config_file_is_private(self, tmp_path: Path) -> None:
        launcher = _Launcher(tmp_path)
        launcher.ready.touch()
        launcher.feed(b"PAYLOAD")

        assert launcher.start().wait(timeout=10) == 0

        assert launcher.config.stat().st_mode & 0o777 == 0o600

    def test_the_arguments_appended_to_the_command_line_do_not_reach_runsc(self, tmp_path: Path) -> None:
        launcher = _Launcher(tmp_path)
        launcher.ready.touch()
        launcher.feed(b"PAYLOAD")

        assert launcher.start("script.py", "--flag").wait(timeout=10) == 0

        assert launcher.calls()[-1].startswith("runsc run --bundle /b config=")

    def test_the_user_arguments_reach_the_guest_command(self, tmp_path: Path) -> None:
        launcher = _Launcher(tmp_path)
        launcher.ready.touch()
        launcher.feed(b"PAYLOAD")

        assert launcher.start("script.py", "--flag").wait(timeout=10) == 0

        assert launcher.guest_args()[:5] == ["python", "-m", "main_sandbox", "script.py", "--flag"]

    def test_the_guest_reads_its_config_from_the_relayed_file_not_the_fifo(self, tmp_path: Path) -> None:
        launcher = _Launcher(tmp_path)
        launcher.ready.touch()
        launcher.feed(b"PAYLOAD")

        assert launcher.start("script.py").wait(timeout=10) == 0

        assert launcher.guest_args()[-2:] == ["--_named-pipe", str(launcher.config)]
        assert str(launcher.fifo) not in launcher.guest_args()

    def test_the_guest_command_is_rewritten_before_runsc_reads_it(self, tmp_path: Path) -> None:
        launcher = _Launcher(tmp_path)
        launcher.runsc.write_text(
            f"#!/bin/sh\ncp {shlex.quote(str(launcher.spec))} {shlex.quote(str(tmp_path / 'seen'))}\n"
        )
        launcher.ready.touch()
        launcher.feed(b"PAYLOAD")

        assert launcher.start("script.py").wait(timeout=10) == 0

        assert "script.py" in (tmp_path / "seen").read_text()

    def test_a_path_with_a_space_is_one_argument(self, tmp_path: Path) -> None:
        spaced = tmp_path / "with space"
        spaced.mkdir()
        launcher = _Launcher(spaced)
        launcher.ready.touch()
        launcher.feed(b"PAYLOAD")

        assert launcher.start().wait(timeout=10) == 0

        assert launcher.calls()[-1].startswith("runsc run --bundle /b config=PAYLOAD")
