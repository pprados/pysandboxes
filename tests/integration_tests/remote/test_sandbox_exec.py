# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Native macOS checks for the generated Seatbelt policy."""

import socket
import subprocess
import sys
import tempfile
import threading
from ipaddress import ip_network
from pathlib import Path

from pysandboxes.all_rules import EmptyRules
from pysandboxes import sandbox, sandboxes
from pysandboxes.guard_files import FSExposeRule, IgnoreRule
from pysandboxes.guard_socket import Action, Direction, Kind, SocketMask, SocketRule
from pysandboxes.remote.sandbox_exec_daemon import _SANDBOX_EXEC, _build_profile
from pysandboxes.sb_types import ConfigLine


@sandbox
def _sse_round_trip() -> str:
    return "sandbox-exec-sse-ok"


def _line(rule: str) -> ConfigLine:
    return ConfigLine(rule, Path("profile"), 1)


def _run(tmp_path: Path, profile: str, code: str) -> subprocess.CompletedProcess[str]:
    profile_path = tmp_path / "test.sb"
    profile_path.write_text(profile, encoding="utf-8")
    profile_path.chmod(0o600)
    return subprocess.run(
        [_SANDBOX_EXEC, "-f", str(profile_path), sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=15,
    )


def _profile(
    tmp_path: Path,
    *,
    file_rules: tuple[FSExposeRule | IgnoreRule, ...] = (),
    socket_rules: tuple[SocketRule, ...] = (),
    use_py_sandbox: bool = False,
) -> str:
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    rules = EmptyRules._replace(
        file_rules=file_rules,
        socket_rules=socket_rules,
        use_py_sandbox=use_py_sandbox,
    )
    return _build_profile(
        rules,
        temp_dir=runtime,
        python_executable=sys.executable,
        python_paths=tuple(path for path in sys.path if path),
        sse_port=1,
    )


def test_filesystem_exposure_and_ignore_are_enforced_by_seatbelt(tmp_path: Path) -> None:
    exposed = tmp_path / "exposed"
    exposed.mkdir()
    ignored = exposed / "secret-é.txt"
    ignored.write_text("secret", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    (exposed / "outside-link.txt").symlink_to(outside)
    rules = (
        FSExposeRule(str(exposed), True, _line(f"expose-rw={exposed}")),
        IgnoreRule(str(exposed / "secret-*.txt"), _line(f"ignore={exposed}/secret-*.txt")),
    )
    profile = _profile(tmp_path, file_rules=rules)
    code = f"""
from pathlib import Path
exposed = Path({str(exposed)!r})
safe = exposed / 'created.txt'
safe.write_text('before')
safe.write_text('after')
safe.rename(exposed / 'renamed.txt')
(exposed / 'renamed.txt').unlink()
checks = []
for path in ({str(ignored)!r}, {str(outside)!r}, {str(exposed / "outside-link.txt")!r}):
    try:
        Path(path).read_text()
    except PermissionError:
        checks.append(True)
    else:
        checks.append(False)
assert all(checks), checks
try:
    (exposed / 'secret-new.txt').write_text('hidden')
except PermissionError:
    pass
else:
    raise AssertionError('new file matching ignore= was writable')
import subprocess, sys
child_code = (
    "from pathlib import Path\\n"
    "try:\\n    Path(" + repr({str(outside)!r}) + ").read_text()\\n"
    "except PermissionError:\\n    print('child-denied')\\n"
    "else:\\n    raise SystemExit('outside read succeeded')"
)
child = subprocess.run([sys.executable, '-c', child_code], capture_output=True, text=True)
assert child.returncode == 0, child.stderr
assert child.stdout.strip() == 'child-denied'
print('files-ok')
"""

    result = _run(tmp_path, profile, code)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "files-ok"


def test_outbound_port_filter_has_a_positive_and_negative_control(tmp_path: Path) -> None:
    servers: list[socket.socket] = []
    for _ in range(2):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen()
        server.settimeout(2)
        servers.append(server)
    allowed_port, denied_port = (server.getsockname()[1] for server in servers)
    accepted: list[socket.socket] = []

    def accept(server: socket.socket) -> None:
        try:
            accepted.append(server.accept()[0])
        except TimeoutError:
            pass

    thread = threading.Thread(target=accept, args=(servers[0],), daemon=True)
    thread.start()
    rule = SocketRule(
        Action.ALLOW,
        SocketMask((Kind.TCP,), ip_network("127.0.0.1/32"), (allowed_port,)),
        (Direction.OUT,),
        _line(f"net=ALLOW|TCP|127.0.0.1|{allowed_port}|OUT"),
    )
    profile = _profile(tmp_path, socket_rules=(rule,))
    code = f"""
import socket
socket.create_connection(('127.0.0.1', {allowed_port}), timeout=2).close()
try:
    socket.create_connection(('127.0.0.1', {denied_port}), timeout=1)
except PermissionError:
    print('ports-ok')
else:
    raise SystemExit('unlisted port connected')
"""

    try:
        result = _run(tmp_path, profile, code)
    finally:
        for server in servers:
            server.close()
        for client in accepted:
            client.close()
        thread.join()

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ports-ok"


def test_malformed_profile_does_not_start_the_command(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    profile = tmp_path / "broken.sb"
    profile.write_text("(version 1)\n(deny default\n", encoding="utf-8")

    result = subprocess.run(
        [_SANDBOX_EXEC, "-f", str(profile), sys.executable, "-c", f"open({str(marker)!r}, 'w')"],
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode != 0
    assert not marker.exists()


def test_sse_daemon_starts_and_removes_its_private_run_directory(tmp_path: Path) -> None:
    profile = tmp_path / "sandbox.profile"
    profile.write_text(
        "\n".join(
            (
                "py-sandbox=true",
                "os-sandbox=sandbox-exec",
                "python-import=*",
                f"expose-ro={Path.cwd()}",
            )
        ),
        encoding="utf-8",
    )
    temp_root = Path(tempfile.gettempdir())
    before = {path.name for path in temp_root.iterdir() if path.name.startswith("tmp")}

    with sandboxes(sandboxes_config=str(profile)):
        assert _sse_round_trip() == "sandbox-exec-sse-ok"

    after = {path.name for path in temp_root.iterdir() if path.name.startswith("tmp")}

    assert after == before
