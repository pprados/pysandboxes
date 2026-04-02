"""
Container tests: docker, podman, and kubernetes.

Controlled by OS_SANDBOX (default: unshare). Failure is determined by the
exit code of the launched process (0 = success).
All logic from test-podman.sh, test-docker.sh and test-kubernetes.sh is
implemented here in Python; no shell scripts are invoked.
"""

import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

logger = logging.getLogger(__name__)

# Project root (parent of tests/)
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
CONTAINER_SCRIPT_DIR = Path(__file__).resolve().parent

# OS_SANDBOX from environment; default unshare
OS_SANDBOX = os.environ.get("OS_SANDBOX", "unshare")

IMAGE_NAME = "python-sb:latest"
PYTHON_SB_ARGS = "--pysandboxes-config=tests/integration_tests/py-sandbox-test.profile"

all_container_worker: list[str] = [
    "docker",
    "podman",
]

all_os_sandbox: list[str] = [
    # firejail is incompatible with containers
    "Subprocess",
    "unshare",
]


def _ensure_image(runtime: str) -> None:
    """Build image with make build-image if not present for the given runtime."""
    r = subprocess.run(
        [runtime, "image", "inspect", IMAGE_NAME],
        capture_output=True,
        cwd=ROOT_DIR,
    )
    if r.returncode == 0:
        return
    logger.error(f"Image {IMAGE_NAME} not found, building with make build-image...")
    subprocess.run(
        ["make", "build-image"],
        cwd=ROOT_DIR,
        check=True,
        capture_output=False,
    )


def _run_container_runtime(
    runtime: str, os_sandbox: str
) -> subprocess.CompletedProcess:
    """Run container test with docker or podman; logic from test-podman.sh."""
    _ensure_image(runtime)

    # Normalize to provider name (lowercase) so config substitution matches providers_factory
    os_sandbox_env = os_sandbox.lower() if os_sandbox != "none" else os_sandbox
    if os_sandbox in ["none", "Subprocess"]:
        py_sandbox_args = "--py-sandbox=true"
    else:
        py_sandbox_args = "--py-sandbox=false"

    tty_flags = ["-it"] if sys.stdin.isatty() else []
    volume_mount = f"{ROOT_DIR}:/app"

    if runtime == "docker":
        prefix = (
            "chmod -R a+rX /app && mkdir -p /app/tmp && chmod -R a+rwX /app/tmp && "
        )
    else:
        prefix = ""

    term = os.environ.get("TERM", "dumb")
    inner_cmd = (
        f"{prefix}"
        f"TERM={term} OS_SANDBOX={os_sandbox_env} My_ENV=1 "
        f"python-sb {py_sandbox_args} {PYTHON_SB_ARGS} -m tests.integration_tests.tst_usage"
    )

    cmd = [
        runtime,
        "run",
        *tty_flags,
        "--rm",
        "--network",
        "bridge",
        "--privileged",
        "-v",
        volume_mount,
        "-w",
        "/app",
        IMAGE_NAME,
        "sh",
        "-c",
        inner_cmd,
    ]

    return subprocess.run(
        cmd,
        cwd=ROOT_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.parametrize("runtime", all_container_worker)
@pytest.mark.parametrize("os_sandbox", all_os_sandbox)
def test_container_runtime(runtime: str, os_sandbox: str) -> None:
    """Run container test with podman or docker; success = exit code 0."""
    try:
        subprocess.run(
            [runtime, "--version"],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip(f"{runtime} not available")

    result = _run_container_runtime(runtime, os_sandbox)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    assert result.returncode == 0, (
        f"Container test ({runtime}, os_sandbox={os_sandbox}) exited with code {result.returncode}. "
        "For unshare, ensure the container has /dev/net/tun and slirp4netns (e.g. use --privileged)."
    )


# --- Kubernetes (logic from test-kubernetes.sh) ---

POD_NAME = "pysandboxes-test"
KUBE_MANIFEST = CONTAINER_SCRIPT_DIR / "kube-pysandboxes.yaml"
WAIT_TIMEOUT = int(os.environ.get("WAIT_TIMEOUT", "120"))
DNS_WAIT = int(os.environ.get("DNS_WAIT", "60"))
EXEC_TIMEOUT = int(os.environ.get("TIMEOUT", "120"))
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
        raise RuntimeError(
            "minikube not found in PATH; install minikube to run Kubernetes tests"
        ) from None
    except subprocess.CalledProcessError:
        print("minikube is not running, starting minikube...")
        subprocess.run(
            ["minikube", "start"],
            cwd=ROOT_DIR,
            check=True,
            capture_output=False,
        )

    print("Waiting for minikube node(s) to be Ready...")
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

    print("Waiting for CoreDNS (kube-dns) to be Ready...")
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


def _ensure_minikube_image() -> None:
    """Build image in minikube's Docker daemon if missing."""
    env = _minikube_docker_env()
    r = subprocess.run(
        ["docker", "image", "inspect", IMAGE_NAME],
        capture_output=True,
        cwd=ROOT_DIR,
        env=env,
    )
    if r.returncode == 0:
        return
    logger.error(
        f"Image {IMAGE_NAME} not found in minikube, building with make build-image-docker..."
    )
    subprocess.run(
        ["make", "build-image-docker"],
        cwd=ROOT_DIR,
        env=env,
        check=True,
        capture_output=False,
    )


def _run_kubernetes_test(os_sandbox: str) -> int:
    """Run Kubernetes pod test; returns exit code (0 = success)."""
    mount_proc: subprocess.Popen | None = None
    rc = 0

    def cleanup() -> None:
        print("\n--- Cleaning up resources ---")
        if mount_proc is not None and mount_proc.poll() is None:
            print(f"Stopping minikube mount (PID: {mount_proc.pid})...")
            mount_proc.terminate()
            try:
                mount_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                mount_proc.kill()
        subprocess.run(
            ["kubectl", "delete", "pod", POD_NAME, "--ignore-not-found", "--now"],
            capture_output=True,
            cwd=ROOT_DIR,
        )

    try:
        _ensure_minikube_ready()
        _ensure_minikube_image()

        print("Starting minikube mount in background...")
        mount_proc = subprocess.Popen(
            ["minikube", "mount", f"{ROOT_DIR}:/mnt/pysandboxes"],
            cwd=ROOT_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)

        print("Applying Kubernetes manifest...")
        subprocess.run(
            ["kubectl", "apply", "-f", str(KUBE_MANIFEST)],
            cwd=ROOT_DIR,
            check=True,
            capture_output=True,
        )

        print(f"Waiting for pod {POD_NAME} to be ready...")
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
            print(f"ERROR: Pod did not become Ready in {WAIT_TIMEOUT}s. Pod status:")
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
            print("Waiting for DNS resolution inside pod...")
            dns_ok = False
            for i in range(1, DNS_WAIT + 1):
                r = subprocess.run(
                    ["kubectl", "exec", POD_NAME, "--", "getent", "hosts", "pypi.org"],
                    capture_output=True,
                    text=True,
                    cwd=ROOT_DIR,
                )
                if r.returncode == 0:
                    print(f"DNS ready after {i}s")
                    dns_ok = True
                    break
                if i == DNS_WAIT:
                    print(f"ERROR: DNS resolution failed after {DNS_WAIT}s")
                    rc = 1
                    break
                time.sleep(1)

            if dns_ok:
                term = os.environ.get("TERM", "xterm")
                os_sandbox_env = (
                    os_sandbox.lower() if os_sandbox != "none" else os_sandbox
                )
                if os_sandbox in ["none", "Subprocess"]:
                    py_sandbox_args = "--py-sandbox=true"
                else:
                    py_sandbox_args = "--py-sandbox=false"
                exec_cmd = (
                    "pip install --no-cache-dir -e . && "
                    f"PYTHONUNBUFFERED=1 TERM={term} OS_SANDBOX={os_sandbox_env} "
                    f"python-sb {py_sandbox_args} {PYTHON_SB_ARGS} -m tests.integration_tests.tst_usage"
                )

                print(f"Executing tests inside the pod (timeout: {EXEC_TIMEOUT}s)...")
                try:
                    r = subprocess.run(
                        [
                            "kubectl",
                            "exec",
                            "-it",
                            POD_NAME,
                            "--",
                            "/bin/bash",
                            "-c",
                            exec_cmd,
                        ],
                        cwd=ROOT_DIR,
                        env={**os.environ, "PYTHONUNBUFFERED": "1"},
                        capture_output=True,
                        text=True,
                        timeout=EXEC_TIMEOUT,
                    )
                    rc = r.returncode
                except subprocess.TimeoutExpired:
                    print(f"ERROR: Test execution timed out after {EXEC_TIMEOUT}s")
                    rc = 1
    except subprocess.TimeoutExpired:
        print(f"ERROR: Test execution timed out after {EXEC_TIMEOUT}s")
        rc = 1
    finally:
        # Fetch pod logs before deleting the pod (kubectl logs fails with NotFound after delete)
        print("--- Pod logs (container stdout/stderr) ---")
        log_result = subprocess.run(
            ["kubectl", "logs", POD_NAME],
            capture_output=True,
            text=True,
            cwd=ROOT_DIR,
        )
        if log_result.returncode == 0 and (log_result.stdout or log_result.stderr):
            print(log_result.stdout or "", end="")
            if log_result.stderr:
                print(log_result.stderr, file=sys.stderr, end="")
        elif (
            log_result.returncode != 0
            and log_result.stderr
            and "NotFound" not in log_result.stderr
        ):
            print(log_result.stderr, file=sys.stderr)
        cleanup()

    print("********* Kubernetes pod test complete *********")
    return rc


@pytest.mark.parametrize("os_sandbox", all_os_sandbox)
def test_container_kubernetes(os_sandbox: str) -> None:
    """Run Kubernetes pod test (minikube); success = exit code 0. Starts minikube if needed."""
    try:
        subprocess.run(
            ["minikube", "version"],
            capture_output=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("minikube not available")

    rc = _run_kubernetes_test(os_sandbox)
    assert rc == 0, f"Kubernetes pod test exited with code {rc}"
