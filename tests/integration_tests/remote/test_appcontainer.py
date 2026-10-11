# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Windows integration tests for the AppContainer OS provider."""

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[3]


def _profile(tmp_path: Path, *rules: str) -> Path:
    profile = tmp_path / "appcontainer.profile"
    profile.write_text(
        "\n".join(
            [
                "py-sandbox=false",
                "os-sandbox=appcontainer",
                "python-import=*",
                f"expose-ro={ROOT_DIR}",
                *rules,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return profile


def _run(tmp_path: Path, profile: Path, code: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={profile}", "-c", code],
        cwd=ROOT_DIR,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _sddl(path: Path) -> str:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "(Get-Acl -LiteralPath $env:PYSB_PATH).Sddl",
        ],
        env={**os.environ, "PYSB_PATH": str(path)},
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.mark.skipif(sys.platform != "win32", reason="AppContainer is Windows-only")
def test_filesystem_read_write_and_deny_rules(tmp_path: Path) -> None:
    read_only = tmp_path / "read-only"
    writable = tmp_path / "writable"
    read_only.mkdir()
    writable.mkdir()
    (read_only / "input.txt").write_text("visible", encoding="utf-8")
    profile = _profile(
        tmp_path,
        f"expose-ro={read_only}",
        f"expose-rw={writable}",
    )
    code = (
        "from pathlib import Path\n"
        f"ro = Path({str(read_only / 'input.txt')!r})\n"
        f"rw = Path({str(writable / 'output.txt')!r})\n"
        "print('READ', ro.read_text())\n"
        "try:\n"
        "    ro.write_text('changed')\n"
        "except OSError as exc:\n"
        "    print('READ_ONLY', type(exc).__name__)\n"
        "else:\n"
        "    print('READ_ONLY_BROKEN')\n"
        "rw.write_text('created')\n"
        "print('WRITE', rw.read_text())\n"
    )

    result = _run(tmp_path, profile, code)

    assert result.returncode == 0, result.stderr
    assert "READ visible" in result.stdout
    assert "READ_ONLY PermissionError" in result.stdout
    assert "WRITE created" in result.stdout
    assert (writable / "output.txt").read_text(encoding="utf-8") == "created"


@pytest.mark.skipif(sys.platform != "win32", reason="AppContainer is Windows-only")
def test_appcontainer_denies_profile_file_and_masks_ignored_file(tmp_path: Path) -> None:
    exposed = tmp_path / "exposed"
    exposed.mkdir()
    ignored = exposed / "ignored.txt"
    ignored.write_text("must stay hidden", encoding="utf-8")
    original_acl = _sddl(exposed)
    profile_secret = Path.home() / f"pysandboxes-appcontainer-{os.getpid()}.secret"
    profile_secret.write_text("profile secret", encoding="utf-8")
    try:
        profile = _profile(tmp_path, f"expose-ro={exposed}", f"ignore={ignored}")
        code = (
            "import ctypes\n"
            "from ctypes import wintypes\n"
            "from pathlib import Path\n"
            f"ignored = Path({str(ignored)!r})\n"
            f"secret = {str(profile_secret)!r}\n"
            "for label, path in (('IGNORE', ignored), ('PROFILE', Path(secret))):\n"
            "    try:\n"
            "        path.read_text()\n"
            "    except OSError as exc:\n"
            "        print(label, 'DENIED', type(exc).__name__)\n"
            "    else:\n"
            "        print(label, 'LEAKED')\n"
            "kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)\n"
            "kernel32.CreateFileW.restype = wintypes.HANDLE\n"
            "kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, "
            "ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)\n"
            "kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)\n"
            "handle = kernel32.CreateFileW(secret, 0x80000000, 1, None, 3, 0x80, None)\n"
            "if handle == wintypes.HANDLE(-1).value:\n"
            "    print('NATIVE DENIED', ctypes.get_last_error())\n"
            "else:\n"
            "    print('NATIVE LEAKED')\n"
            "    kernel32.CloseHandle(handle)\n"
        )

        result = _run(tmp_path, profile, code)

        assert result.returncode == 0, result.stderr
        assert "IGNORE DENIED" in result.stdout
        assert "PROFILE DENIED" in result.stdout
        assert "NATIVE DENIED" in result.stdout
        assert "LEAKED" not in result.stdout
        restored_acl = _sddl(exposed)
        assert restored_acl.replace("D:AI", "D:") == original_acl.replace("D:AI", "D:")
        assert ignored.read_text(encoding="utf-8") == "must stay hidden"
    finally:
        profile_secret.unlink(missing_ok=True)


@pytest.mark.skipif(sys.platform != "win32", reason="AppContainer is Windows-only")
def test_concurrent_runs_keep_their_filesystem_grants(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    run_dirs = [tmp_path / f"run-{index}" for index in range(2)]
    for run_dir in run_dirs:
        run_dir.mkdir()
    profiles = [_profile(run_dir, f"expose-rw={shared}") for run_dir in run_dirs]
    cases = [
        (profile, f"from pathlib import Path; Path({str(shared / f'concurrent-{index}.txt')!r}).write_text('ok')")
        for index, profile in enumerate(profiles)
    ]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda case: _run(tmp_path, case[0], case[1]), cases))

    for result in results:
        assert result.returncode == 0, result.stderr
    assert all((shared / f"concurrent-{index}.txt").read_text(encoding="utf-8") == "ok" for index in range(2))


@pytest.mark.skipif(sys.platform != "win32", reason="AppContainer is Windows-only")
def test_killing_trampoline_kills_appcontainer_child(tmp_path: Path) -> None:
    import psutil

    child_pid_path = tmp_path / "child.pid"
    profile = _profile(tmp_path, f"expose-rw={tmp_path}")
    code = (
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
        f"Path({str(child_pid_path)!r}).write_text(str(child.pid))\n"
        "time.sleep(600)\n"
    )
    runner = subprocess.Popen(
        [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={profile}", "-c", code],
        cwd=ROOT_DIR,
        env=os.environ.copy(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    trampoline: psutil.Process | None = None
    child_pid: int | None = None
    deadline = time.monotonic() + 90
    try:
        while time.monotonic() < deadline:
            if child_pid_path.exists():
                child_pid = int(child_pid_path.read_text(encoding="utf-8"))
                for process in psutil.process_iter(("cmdline",)):
                    try:
                        if "pysandboxes.remote.appcontainer_launcher" in " ".join(process.info["cmdline"] or []):
                            trampoline = process
                            break
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        continue
                if trampoline is not None:
                    break
            if runner.poll() is not None:
                break
            time.sleep(0.2)
        assert child_pid is not None, "the AppContainer child did not report its PID"
        assert trampoline is not None, "the AppContainer trampoline process was not found"

        trampoline.kill()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and psutil.pid_exists(child_pid):
            time.sleep(0.1)
        assert not psutil.pid_exists(child_pid), "the AppContainer child outlived its trampoline"
    finally:
        runner.kill()
        runner.wait(timeout=10)
