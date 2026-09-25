"""
Container tests: docker, podman, and kubernetes.

Controlled by OS_SANDBOX (default: unshare). Failure is determined by the
exit code of the launched process (0 = success).
All logic from test-podman.sh, test-docker.sh and test-kubernetes.sh is
implemented here in Python; no shell scripts are invoked.
"""

import logging
import os
import pty
import re
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import TextIO

import pytest

from pysandboxes.remote.landlock_daemon import landlock_user_available

logger = logging.getLogger(__name__)


def _terminal_newline_before_log() -> None:
    """Finish any in-progress QEMU serial line (often ends with \\r only) before host logs.

    Mixing pytest logging with ``-nographic`` serial output leaves the cursor mid-line;
    the next ``INFO`` line then appears shifted or stacked, as if nothing advanced.
    Use stderr only so a merged ``2>&1`` pipe does not get two blank lines.
    """
    try:
        sys.stderr.write("\r\n")
        sys.stderr.flush()
    except OSError:
        pass


# Project root (parent of tests/)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONTAINER_SCRIPT_DIR = Path(__file__).resolve().parent

# OS_SANDBOX from environment; default unshare
OS_SANDBOX = os.environ.get("OS_SANDBOX", "unshare")


# One image per OS provider; names are python-sb-<provider>
# (e.g. python-sb-unshare, python-sb-qemu), :latest tag.
def _image_for_os_provider(os_sandbox: str) -> str:
    """Return the container image name for the given OS_SANDBOX provider (e.g. unshare -> python-sb-unshare:latest)."""
    provider = (os_sandbox or "base").lower()
    if provider in ("none", "subprocess"):
        return "python-sb:latest"
    return f"python-sb-{provider}:latest"


PYTHON_SB_ARGS = "--pysandboxes-config=tests/integration_tests/py-sandbox-test.profile"

all_container_worker: list[str] = [
    "docker",
    "podman",
]


# firejail is incompatible with containers
all_os_sandbox_provider: list[str] = [
    "none",
    "landlock",
    "unshare",
    "bwrap",
    "qemu",
]

# Providers that cannot run in an unprivileged container: they create their own namespaces
# (unshare) or need mount privileges the default container does not grant (bwrap).
needs_privileged: frozenset[str] = frozenset({"unshare", "bwrap"})


# os_sandbox,py_sandbox,privileged (pytest.param tuples for parametrize)
# QEMU in Podman: nested VM + tst_usage may need a higher CONTAINER_RUN_TIMEOUT (see wiki/qemu.md).
# Run on host: pytest tests/integration_tests/test_usage_with_providers.py -k qemu
def _all_os_sandbox_params() -> list:
    """Full os_sandbox x py_sandbox x privileged matrix; unviable rows are declared xfail, not run."""
    rows = []
    for os_sandbox in all_os_sandbox_provider:
        for py_sandbox in (True, False):
            for privileged in (True, False):
                marks = []
                if not privileged and os_sandbox in needs_privileged:
                    marks.append(
                        pytest.mark.xfail(
                            reason=f"{os_sandbox} needs a privileged container (namespaces, mounts)",
                            run=False,
                        )
                    )
                rows.append(pytest.param(os_sandbox, py_sandbox, privileged, marks=marks))
    return rows


all_os_sandbox: list = _all_os_sandbox_params()


def _k8s_exec_timeout_seconds(os_sandbox: str) -> int:
    if os_sandbox.lower() == "qemu":
        return int(os.environ.get("K8S_QEMU_EXEC_TIMEOUT", "900"))
    return int(os.environ.get("TIMEOUT", "120"))


# TODO: test with split mode

# Fallback DNS when host has no usable nameservers (e.g. CI, minimal env)
_DNS_FALLBACK = ("8.8.8.8", "8.8.4.4")


def _host_dns_servers() -> list[str]:
    """Read nameservers from the host so the container uses platform DNS.

    Tries /etc/resolv.conf first, then resolvectl (systemd-resolved).
    Skips 127.0.0.0/8 and ::1 which often do not work inside containers.
    Returns _DNS_FALLBACK if no usable nameserver is found.
    """
    found: list[str] = []

    # 1. /etc/resolv.conf
    resolv = Path("/etc/resolv.conf")
    if resolv.exists():
        for line in resolv.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith("nameserver "):
                ip = line.split(maxsplit=1)[1].strip()
                if ip and ip not in found:
                    found.append(ip)

    # 2. resolvectl (systemd-resolved) if resolv.conf had no usable entries
    if not found:
        try:
            r = subprocess.run(
                ["resolvectl", "status"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if r.returncode == 0 and r.stdout:
                # Lines like "DNS Servers: 10.0.2.3" or "Current DNS Server: 10.0.2.3"
                for line in r.stdout.splitlines():
                    if ":" in line and "dns" in line.lower():
                        part = line.split(":", 1)[1].strip()
                        for token in part.split():
                            if token and token not in found:
                                found.append(token)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # Skip loopback addresses (often don't work in container)
    def _is_loopback(ip: str) -> bool:
        if ip == "::1":
            return True
        if ip.startswith("127."):
            return True
        return False

    usable = [ip for ip in found if not _is_loopback(ip)]
    if not usable:
        return list(_DNS_FALLBACK)
    return usable


# Hostname from py-sandbox-test.profile that require resolution at config load time
_PROFILE_RESOLVE_HOSTS = ("github.com",)


def _is_ipv4(addr: str) -> bool:
    """Return True if addr looks like an IPv4 address."""
    return "." in addr and ":" not in addr and len(addr) <= 15


def _resolve_on_host(hostname: str, timeout: float = 5.0) -> str | None:
    """Resolve hostname on the host; return one IPv4 address or None on failure.

    Prefer IPv4 so --add-host is unambiguous and socket.gethostbyname() in the test works.
    """
    # Prefer getent ahostsv4 for IPv4-only; fallback to getent hosts and take first IPv4
    for getent_cmd, take_ipv4 in [
        (["getent", "ahostsv4", hostname], True),
        (["getent", "hosts", hostname], True),
    ]:
        try:
            r = subprocess.run(
                getent_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if r.returncode == 0 and r.stdout:
                for line in r.stdout.strip().splitlines():
                    parts = line.split()
                    if parts:
                        ip = parts[0]
                        if take_ipv4 and _is_ipv4(ip):
                            return ip
                        if not take_ipv4:
                            return ip
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    try:
        infos = socket.getaddrinfo(hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        if infos:
            addr = infos[0][4][0]
            return addr if isinstance(addr, str) else None
    except (socket.gaierror, OSError):
        pass
    return None


def _add_host_flags() -> list[str]:
    """Resolve profile hostname on the host and return --add-host flags for the container.

    So the container does not need DNS for config parsing; platform resolution is done on the host.
    """
    flags: list[str] = []
    for hostname in _PROFILE_RESOLVE_HOSTS:
        ip = _resolve_on_host(hostname)
        if ip:
            flags.extend(["--add-host", f"{hostname}:{ip}"])
        else:
            logger.warning(
                "Could not resolve %s on host; container may fail config parsing",
                hostname,
            )
    return flags


# How much of a failing container's output to put in the report. The interesting part
# (traceback, last [pysandbox-9p] mount, the guest's final words) is at the end.
CONTAINER_OUTPUT_TAIL_LINES = int(os.environ.get("CONTAINER_OUTPUT_TAIL_LINES", "60"))


def _open_ctty() -> TextIO | None:
    """The controlling terminal, to mirror the run on, or None when there is none.

    Set ``CONTAINER_TEST_NO_CTTY=1`` to skip it (CI has no TTY to write to).
    """
    if os.environ.get("CONTAINER_TEST_NO_CTTY", "").lower() in ("1", "true", "yes"):
        return None
    try:
        return open(os.ctermid(), "w", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return None


class _PtyStream:
    """One of the container's output streams, on its own pty, drained by a thread.

    The pty keeps ``isatty()`` true for the child -- python-sb in CLI mode asks. The
    thread is what makes that safe: an undrained pty fills its buffer and the container
    blocks on write, exactly the deadlock a pipe would have caused. What it reads goes
    to ``mirror`` (live view) and to ``tail`` (the failure report).
    """

    def __init__(self, name: str, mirror: TextIO | None) -> None:
        self.name = name
        self.tail: deque[str] = deque(maxlen=CONTAINER_OUTPUT_TAIL_LINES)
        self.master_fd, self.slave_fd = pty.openpty()
        self._closed = False
        self._mirror = mirror
        self._thread = threading.Thread(
            target=self._drain,
            name=f"container-test-{name}",
            daemon=True,
        )
        self._thread.start()

    def _drain(self) -> None:
        pending = ""
        while True:
            try:
                chunk = os.read(self.master_fd, 65536)
            except OSError:  # master closed by close(), or the slave end went away
                break
            if not chunk:
                break
            text = chunk.decode("utf-8", errors="replace")
            if self._mirror is not None:
                try:
                    self._mirror.write(text)
                except OSError:
                    self._mirror = None
            pending += text
            *lines, pending = pending.split("\n")
            # A pty translates \n to \r\n on the way out; keep the report free of them.
            self.tail.extend(line.rstrip("\r") for line in lines)
        if pending:
            self.tail.append(pending.rstrip("\r"))

    def close(self) -> None:
        """Close the slave so the drain sees EOF, let it finish, then drop the master.

        Idempotent: the failure paths close early, to report a complete tail, and the
        ``finally`` closes again for the runs that succeeded.
        """
        if self._closed:
            return
        self._closed = True
        for fd in (self.slave_fd, self.master_fd):
            try:
                os.close(fd)
            except OSError:
                pass
        self._thread.join(timeout=5)


def _report_container_output(out: _PtyStream, err: _PtyStream, runtime: str, os_sandbox: str) -> None:
    """Log each stream's tail so pytest shows it under Captured log.

    Mirroring to the terminal alone left the report empty: a row that timed out said
    ``TimeoutExpired`` and not one line of what the container had done.
    """
    reported = False
    for stream in (err, out):  # stderr first: that is where a failure usually explains itself
        stream.close()  # let the drain finish, so the tail is the real end of the run
        if stream.tail:
            reported = True
            logger.error(
                "container-tests: last %d %s lines from %s (os_sandbox=%s):\n%s",
                len(stream.tail),
                stream.name,
                runtime,
                os_sandbox,
                "\n".join(stream.tail),
            )
    if not reported:
        logger.error(
            "container-tests: %s (os_sandbox=%s) produced no output at all. For qemu this is "
            "expected unless qemu.show_boot_console=true: the daemon sends the VM console to "
            "DEVNULL otherwise (remote/qemu_sse_daemon.py).",
            runtime,
            os_sandbox,
        )


# Timeout for building the container image when missing (avoid indefinite hang)
BUILD_IMAGE_TIMEOUT = 600  # seconds

# Timeout for the container run (inner python-sb + integration tests). Default 2 minutes.
# Override with CONTAINER_RUN_TIMEOUT (seconds). Nested QEMU without KVM (TCG) may need more; see wiki/qemu.md.
CONTAINER_RUN_TIMEOUT = int(os.environ.get("CONTAINER_RUN_TIMEOUT", "120"))


def _qemu_kvm_run_extra_flags() -> list[str]:
    """Pass host KVM into the container so nested qemu-system can use -enable-kvm (not TCG)."""
    extra: list[str] = []
    kvm = Path("/dev/kvm")
    if not kvm.exists():
        logger.warning(
            "container-tests (qemu): host has no /dev/kvm; nested QEMU will use TCG "
            "(often exceeds %ss). Pass KVM or raise CONTAINER_RUN_TIMEOUT.",
            CONTAINER_RUN_TIMEOUT,
        )
        return extra
    extra.extend(["--device", "/dev/kvm"])
    try:
        gid = kvm.stat().st_gid
        extra.extend(["--group-add", str(gid)])
        logger.debug(
            "container-tests (qemu): --device /dev/kvm --group-add %s (nested KVM)",
            gid,
        )
    except OSError as e:
        logger.warning("container-tests (qemu): could not stat /dev/kvm for --group-add: %s", e)
    return extra


def _ensure_image(runtime: str, image_name: str, os_sandbox: str) -> None:
    """Build the provider image with make build-image-<provider> if not present for the given runtime."""
    r = subprocess.run(
        [runtime, "image", "inspect", image_name],
        capture_output=True,
        cwd=ROOT_DIR,
    )
    if r.returncode == 0:
        return
    provider = (os_sandbox or "base").lower()
    if provider == "none":
        provider = "base"
    make_target = f"build-image-{provider}"
    logger.error("Image %s not found, building with make %s...", image_name, make_target)
    subprocess.run(
        ["make", make_target],
        cwd=ROOT_DIR,
        check=True,
        capture_output=False,
        timeout=BUILD_IMAGE_TIMEOUT,
    )


def _run_container_runtime(
    runtime: str, os_sandbox: str, py_sandbox: bool, privileged: bool
) -> subprocess.CompletedProcess:
    """Run container test with docker or podman; logic from test-podman.sh."""
    image_name = _image_for_os_provider(os_sandbox)
    _ensure_image(runtime, image_name, os_sandbox)

    # Normalize to provider name (lowercase) so config substitution matches providers_factory
    os_sandbox_env = os_sandbox.lower() if os_sandbox != "none" else os_sandbox
    py_sandbox_args = f"--py-sandbox={py_sandbox}"

    tty_flags = ["-it"] if sys.stdin.isatty() else []
    volume_mount = f"{ROOT_DIR}:/app"

    if runtime == "docker":
        prefix = "chmod -R a+rX /app && mkdir -p /app/tmp && chmod -R a+rwX /app/tmp && "
    else:
        prefix = ""

    term = os.environ.get("TERM", "xterm-256color")
    # PYTHONPATH=/app so -m tests.integration_tests.tst_usage finds the tests package
    # QEMU: file_rules root is mounted at /app in the VM (same strategy as bwrap)
    # py-sandbox-test.profile uses qemu.show_boot_console=true (VM serial + verbose NoCloud seed).
    inner_cmd = (
        f"{prefix}"
        f"PYTHONPATH=/app TERM={term} OS_SANDBOX={os_sandbox_env} My_ENV=1 "
        f"python-sb {py_sandbox_args} {PYTHON_SB_ARGS} -m tests.integration_tests.tst_usage"
    )

    privileged_flag = ["--privileged"] if privileged else []
    # Nested QEMU needs host KVM in the container; otherwise TCG exceeds typical timeouts.
    kvm_flags = _qemu_kvm_run_extra_flags() if os_sandbox.lower() == "qemu" else []
    # Use host/platform DNS so config parsing can resolve hostname
    dns_servers = _host_dns_servers()
    dns_flags = [arg for s in dns_servers for arg in ("--dns", s)]
    # Resolve profile hostname on the host and inject so container does not need DNS at config load
    add_host_flags = _add_host_flags()
    # bwrap: host net for slirp/iptables. qemu: host net avoids double-NAT (Podman bridge + QEMU user)
    # which can stall nested tst_usage for a long time.
    network_mode = "host" if os_sandbox in ("bwrap", "qemu") else "bridge"
    cmd = [
        runtime,
        "run",
        *tty_flags,
        *privileged_flag,
        *kvm_flags,
        "--rm",
        "--network",
        network_mode,
        *dns_flags,
        *add_host_flags,
        "-v",
        volume_mount,
        "-w",
        "/app",
        image_name,
        "sh",
        "-c",
        inner_cmd,
    ]

    if os.environ.get("CONTAINER_TEST_TRACE_CMD") == "1":
        logger.warning("container-tests podman/docker cmd: %s", shlex.join(cmd))

    logger.debug(
        "container-tests: starting %s run image=%s os_sandbox=%s timeout=%ss",
        runtime,
        image_name,
        os_sandbox,
        CONTAINER_RUN_TIMEOUT,
    )

    # Do not use capture_output=True: the container produces a lot of log output (DEBUG).
    # With pipes, the buffer (~64KB) can fill and the container blocks on write → deadlock.
    # A file has no such limit and, unlike the TTY, survives the run to be reported.
    stop_heartbeat = threading.Event()

    def _heartbeat() -> None:
        interval = int(os.environ.get("CONTAINER_TEST_HEARTBEAT_SEC", "60"))
        if interval <= 0:
            return
        start = time.monotonic()
        while not stop_heartbeat.wait(interval):
            _terminal_newline_before_log()
            elapsed = time.monotonic() - start
            logger.debug(
                "container-tests: %s still running (os_sandbox=%s, elapsed=%.0fs, "
                "timeout=%ss; nested QEMU may need a higher CONTAINER_RUN_TIMEOUT "
                "if TCG is slow)",
                runtime,
                os_sandbox,
                elapsed,
                CONTAINER_RUN_TIMEOUT,
            )

    hb = threading.Thread(target=_heartbeat, name="container-test-heartbeat", daemon=True)
    hb.start()
    # A pty per stream, not a file and not one shared fd: python-sb in CLI mode checks
    # isatty(), so the child must still see a terminal, and stdout must stay separate
    # from stderr -- merging them is what QEMU already does to the guest, and the host
    # side has no business repeating it. Each master end is drained by a thread, which
    # mirrors the run live and keeps its tail for the failure report.
    mirror = _open_ctty()
    out = _PtyStream("stdout", mirror)
    err = _PtyStream("stderr", mirror)
    try:
        completed = subprocess.run(
            cmd,
            cwd=ROOT_DIR,
            env=os.environ.copy(),
            stdout=out.slave_fd,
            stderr=err.slave_fd,
            timeout=CONTAINER_RUN_TIMEOUT,
        )
        _terminal_newline_before_log()
        logger.debug(
            "container-tests: %s finished os_sandbox=%s returncode=%s",
            runtime,
            os_sandbox,
            completed.returncode,
        )
        if completed.returncode != 0:
            _report_container_output(out, err, runtime, os_sandbox)
        return completed
    except subprocess.TimeoutExpired as e:
        _terminal_newline_before_log()
        logger.error(
            "container-tests: %s timed out after %ss (os_sandbox=%s)",
            runtime,
            CONTAINER_RUN_TIMEOUT,
            os_sandbox,
        )
        # The container is what knows why it hung; without this the report is the
        # TimeoutExpired and nothing else, which is how twelve qemu rows failed
        # silently for a whole test run.
        _report_container_output(out, err, runtime, os_sandbox)
        raise e
    finally:
        stop_heartbeat.set()
        out.close()
        err.close()
        if mirror is not None:
            try:
                mirror.close()
            except OSError:
                pass


@pytest.mark.parametrize("os_sandbox,py_sandbox,privileged", all_os_sandbox)
@pytest.mark.parametrize("runtime", all_container_worker)
def test_container_runtime(runtime: str, os_sandbox: str, py_sandbox: bool, privileged: bool) -> None:
    """Run container test with podman or docker; success = exit code 0.

    Nested output is collected to a temporary file and, when the row fails, its tail is
    logged so the report says what the container did (``CONTAINER_OUTPUT_TAIL_LINES``
    sets how much). QEMU: with
    ``qemu.show_boot_console=false``, the host only
    forwards lines between ``[PYSANDBOXES]PYTHON_OUTPUT_START`` and ``END``;
    for full VM boot trace, set ``qemu.show_boot_console=true`` (see wiki/qemu.md).

    Parametrization is currently limited to ``qemu`` only (see ``_all_os_sandbox_params``).
    For faster runs, re-enable ``none`` / ``unshare`` / ``bwrap`` there. On the host,
    ``tests/integration_tests/test_usage_with_providers.py -k qemu`` avoids nested Podman.
    Optional: ``CONTAINER_TEST_TRACE_CMD=1`` logs the full ``podman run`` argv;
    ``CONTAINER_TEST_HEARTBEAT_SEC=N`` prints a line to **stderr** on the host every N seconds
    while ``podman run`` is still running (default 60; set 0 to disable)—confirms the outer
    process is not stuck
    in pytest, not that the nested guest is making progress. Nested QEMU: ``QemuSSEDaemon`` drains
    the VM serial to stderr and logs each line at DEBUG (``[qemu-serial]``) when
    ``qemu.show_boot_console=true``. ``py-sandbox-test.profile`` sets it.
    """

    try:
        subprocess.run(
            [runtime, "--version"],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip(f"{runtime} not available")

    if os_sandbox == "landlock" and not landlock_user_available():
        pytest.skip("Landlock not available (kernel < 5.13 or not Linux)")

    result = _run_container_runtime(runtime, os_sandbox, py_sandbox, privileged)
    assert result.returncode == 0, (
        f"Container test ({runtime}, os_sandbox={os_sandbox}) exited with code {result.returncode}. "
        "For unshare, ensure the container has /dev/net/tun and slirp4netns (e.g. use --privileged). "
        "For QEMU in a container, if the guest segfaults, see wiki/qemu.md (nested QEMU) and "
        "enable qemu.show_boot_console=true in the profile."
    )


# --- Kubernetes (logic from test-kubernetes.sh) ---

POD_NAME = "pysandboxes-test"
KUBE_MANIFEST = CONTAINER_SCRIPT_DIR / "kube-pysandboxes.yaml"
WAIT_TIMEOUT = int(os.environ.get("WAIT_TIMEOUT", "120"))
DNS_WAIT = int(os.environ.get("DNS_WAIT", "60"))

# The elevated block of the pod: `privileged`, the added capabilities and the disabled
# seccomp filter. Matched as a whole because dropping only `privileged: true` would leave
# SYS_ADMIN, NET_ADMIN and seccompProfile: Unconfined in place: the pod would still be
# elevated and an unprivileged row would pass for the wrong reason.
_SECURITY_CONTEXT_RE = re.compile(r"^      securityContext:\n(?:^ {8,}.*\n)*", re.MULTILINE)


def _kube_manifest_text(image_name: str, privileged: bool) -> str:
    """Return the pod manifest for one matrix row: image substituted, privileges applied."""
    text = KUBE_MANIFEST.read_text(encoding="utf-8")
    text, count = re.subn(r"image:\s*[\w/:.-]+", f"image: {image_name}", text, count=1)
    assert count == 1, f"no image line to substitute in {KUBE_MANIFEST}"
    if not privileged:
        text, count = _SECURITY_CONTEXT_RE.subn("", text)
        assert count == 1, f"no securityContext block to remove in {KUBE_MANIFEST}"
    return text


MINIKUBE_NODE_READY_TIMEOUT = int(os.environ.get("MINIKUBE_NODE_READY_TIMEOUT", "120"))
MINIKUBE_DNS_READY_TIMEOUT = int(os.environ.get("MINIKUBE_DNS_READY_TIMEOUT", "120"))


def _minikube_docker_env() -> dict[str, str]:
    """Return env dict with minikube docker-env variables applied."""
    result = subprocess.run(
        ["minikube", "docker-env"],
        capture_output=True,
        text=True,
        cwd=ROOT_DIR,
    )
    if result.returncode != 0:
        raise RuntimeError(f"minikube docker-env failed: {result.stderr}")
    env = os.environ.copy()
    # Parse "export VAR=value" lines
    for line in result.stdout.splitlines():
        m = re.match(r"export\s+(\w+)=(.*)$", line.strip())
        if m:
            key, value = m.group(1), m.group(2).strip().strip("'\"")
            env[key] = value
    return env


def _ensure_minikube_ready() -> None:
    """Verify minikube is available, start it if not running, wait for node and CoreDNS ready."""
    try:
        subprocess.run(
            ["minikube", "status"],
            capture_output=True,
            check=True,
            cwd=ROOT_DIR,
        )
    except FileNotFoundError:
        raise RuntimeError("minikube not found in PATH; install minikube to run Kubernetes tests") from None
    except subprocess.CalledProcessError:
        logger.info("minikube is not running, starting minikube...")
        subprocess.run(
            ["minikube", "start"],
            cwd=ROOT_DIR,
            check=True,
            capture_output=False,
        )

    logger.info("Waiting for minikube node(s) to be Ready...")
    r = subprocess.run(
        [
            "kubectl",
            "wait",
            "--for=condition=Ready",
            "nodes",
            "--all",
            f"--timeout={MINIKUBE_NODE_READY_TIMEOUT}s",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT_DIR,
    )
    if r.returncode != 0:
        raise RuntimeError(
            f"minikube nodes did not become Ready in {MINIKUBE_NODE_READY_TIMEOUT}s: {r.stderr or r.stdout}"
        )

    logger.info("Waiting for CoreDNS (kube-dns) to be Ready...")
    subprocess.run(
        [
            "kubectl",
            "wait",
            "--for=condition=Ready",
            "pod",
            "-l",
            "k8s-app=kube-dns",
            "-n",
            "kube-system",
            f"--timeout={MINIKUBE_DNS_READY_TIMEOUT}s",
        ],
        capture_output=True,
        cwd=ROOT_DIR,
    )
    # Non-fatal: cluster may still work; DNS can lag slightly after node ready


def _assert_minikube_image(os_sandbox: str) -> None:
    """Require the provider image in minikube's Docker daemon (built by Makefile, not by tests)."""
    env = _minikube_docker_env()
    image_ref = _image_for_os_provider(os_sandbox)
    inspect = subprocess.run(
        ["docker", "image", "inspect", image_ref],
        cwd=ROOT_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if inspect.returncode != 0:
        raise RuntimeError(
            f"Image {image_ref!r} not found in minikube's Docker daemon. "
            "Build with: eval $(minikube docker-env) && make build-image-docker "
            "(or run make container-tests, which runs minikube-build-images)."
        )


def _stop_minikube_mount(mount_proc: subprocess.Popen) -> None:
    """Stop ``minikube mount`` and any child processes (FUSE/SSH helpers).

    A plain ``terminate()`` on the parent often leaves descendants running, which can
    block pytest or the shell from exiting after the test completes.
    """
    if mount_proc.poll() is not None:
        return
    logger.info(f"Stopping minikube mount (PID: {mount_proc.pid})...")
    if os.name == "posix":
        try:
            os.killpg(mount_proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            mount_proc.terminate()
        try:
            mount_proc.wait(timeout=12)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(mount_proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            mount_proc.kill()
        try:
            mount_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            pass
    else:
        mount_proc.terminate()
        try:
            mount_proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            mount_proc.kill()
            try:
                mount_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                pass


def _run_kubernetes_test(os_sandbox: str, py_sandbox: bool, privileged: bool) -> int:
    """Run Kubernetes pod test; returns exit code (0 = success)."""

    mount_proc: subprocess.Popen | None = None
    rc = 0

    def cleanup() -> None:
        logger.info("\n--- Cleaning up resources ---")
        if mount_proc is not None:
            _stop_minikube_mount(mount_proc)
        subprocess.run(
            ["kubectl", "delete", "pod", POD_NAME, "--ignore-not-found", "--now"],
            capture_output=True,
            cwd=ROOT_DIR,
            timeout=120,
        )

    try:
        _ensure_minikube_ready()
        _assert_minikube_image(os_sandbox)

        logger.info("Starting minikube mount in background...")
        mount_proc = subprocess.Popen(
            ["minikube", "mount", f"{ROOT_DIR}:/mnt/pysandboxes"],
            cwd=ROOT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(3)

        image_name = _image_for_os_provider(os_sandbox)
        manifest_text = _kube_manifest_text(image_name, privileged)
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".yaml",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(manifest_text)
            manifest_path = f.name
        try:
            logger.info(f"Applying Kubernetes manifest (image={image_name})...")
            subprocess.run(
                ["kubectl", "apply", "-f", manifest_path],
                cwd=ROOT_DIR,
                check=True,
                capture_output=True,
            )
        finally:
            Path(manifest_path).unlink(missing_ok=True)

        logger.info(f"Waiting for pod {POD_NAME} to be ready...")
        r = subprocess.run(
            [
                "kubectl",
                "wait",
                "--for=condition=Ready",
                f"pod/{POD_NAME}",
                f"--timeout={WAIT_TIMEOUT}s",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT_DIR,
        )
        if r.returncode != 0:
            logger.error(f"ERROR: Pod did not become Ready in {WAIT_TIMEOUT}s. Pod status:")
            subprocess.run(
                ["kubectl", "get", "pod", POD_NAME, "-o", "wide"],
                capture_output=False,
                cwd=ROOT_DIR,
            )
            subprocess.run(
                ["kubectl", "describe", "pod", POD_NAME],
                capture_output=False,
                cwd=ROOT_DIR,
            )
            rc = 1
        else:
            logger.info("Waiting for DNS resolution inside pod...")
            dns_ok = False
            for i in range(1, DNS_WAIT + 1):
                r = subprocess.run(
                    ["kubectl", "exec", POD_NAME, "--", "getent", "hosts", "pypi.org"],
                    capture_output=True,
                    text=True,
                    cwd=ROOT_DIR,
                )
                if r.returncode == 0:
                    logger.debug(f"DNS ready after {i}s")
                    dns_ok = True
                    break
                if i == DNS_WAIT:
                    logger.error(f"ERROR: DNS resolution failed after {DNS_WAIT}s")
                    rc = 1
                    break
                time.sleep(1)

            if dns_ok:
                term = os.environ.get("TERM", "xterm")
                os_sandbox_env = os_sandbox.lower() if os_sandbox != "none" else os_sandbox
                py_sandbox_args = f"--py-sandbox={py_sandbox}"
                exec_timeout = _k8s_exec_timeout_seconds(os_sandbox)
                exec_cmd = (
                    "pip install --no-cache-dir -e . && "
                    f"PYTHONUNBUFFERED=1 TERM={term} OS_SANDBOX={os_sandbox_env} "
                    f"python-sb {py_sandbox_args} {PYTHON_SB_ARGS} -m tests.integration_tests.tst_usage"
                )

                logger.info(
                    f"Executing tests inside the pod (timeout: {exec_timeout}s, " f"os_sandbox={os_sandbox})..."
                )
                logger.info(
                    "kubectl exec output streams below (no pipe capture — avoids deadlock "
                    "and long QEMU/TCG silence). Nested qemu can take many minutes.",
                )
                stop_k8s_hb = threading.Event()

                def _k8s_exec_heartbeat() -> None:
                    interval = int(os.environ.get("CONTAINER_TEST_HEARTBEAT_SEC", "60"))
                    if interval <= 0:
                        return
                    start = time.monotonic()
                    while not stop_k8s_hb.wait(interval):
                        _terminal_newline_before_log()
                        elapsed = time.monotonic() - start
                        logger.debug(
                            "k8s-test: kubectl exec still running " "(os_sandbox=%s, elapsed=%.0fs, timeout=%ss)",
                            os_sandbox,
                            elapsed,
                            exec_timeout,
                        )

                hb_k8s = threading.Thread(
                    target=_k8s_exec_heartbeat,
                    name="k8s-exec-heartbeat",
                    daemon=True,
                )
                hb_k8s.start()
                try:
                    # Inherit stdout/stderr: do not use capture_output or PIPE — nested QEMU
                    # can fill ~64KiB quickly and block the guest; user sees live progress.
                    exec_result = subprocess.run(
                        [
                            "kubectl",
                            "exec",
                            POD_NAME,
                            "--",
                            "/bin/bash",
                            "-c",
                            exec_cmd,
                        ],
                        cwd=ROOT_DIR,
                        env={**os.environ, "PYTHONUNBUFFERED": "1"},
                        timeout=exec_timeout,
                    )
                    rc = exec_result.returncode
                    if rc != 0:
                        logger.debug(
                            f"ERROR: kubectl exec exited {rc} (os_sandbox={os_sandbox})",
                        )
                except subprocess.TimeoutExpired:
                    logger.debug(
                        f"ERROR: Test execution timed out after {exec_timeout}s " f"(os_sandbox={os_sandbox})",
                    )
                    rc = 1
                finally:
                    stop_k8s_hb.set()
    except subprocess.TimeoutExpired:
        logger.debug("ERROR: A subprocess timed out during the Kubernetes pod test")
        rc = 1
    finally:
        # Fetch pod logs before deleting the pod (kubectl logs fails with NotFound after delete)
        logger.info("--- Pod logs (container stdout/stderr) ---")
        log_result = subprocess.run(
            ["kubectl", "logs", POD_NAME],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=ROOT_DIR,
        )
        if log_result.returncode == 0 and (log_result.stdout or log_result.stderr):
            print(log_result.stdout or "", end="")
            if log_result.stderr:
                print(log_result.stderr, file=sys.stderr, end="")
        elif log_result.returncode != 0 and log_result.stderr and "NotFound" not in log_result.stderr:
            print(log_result.stderr, file=sys.stderr)
        cleanup()

    logger.info("********* Kubernetes pod test complete *********")
    return rc


@pytest.mark.parametrize("os_sandbox,py_sandbox,privileged", all_os_sandbox)
def test_container_kubernetes(os_sandbox: str, py_sandbox: bool, privileged: bool) -> None:
    """Run Kubernetes pod test (minikube); success = exit code 0. Starts minikube if needed."""

    try:
        subprocess.run(
            ["minikube", "version"],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("minikube not available")

    rc = _run_kubernetes_test(os_sandbox, py_sandbox, privileged)
    assert rc == 0, f"Kubernetes pod test exited with code {rc}"
