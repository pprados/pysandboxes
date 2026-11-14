# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Measure the start-up time of every OS provider, cold and warm.

Cold: a fresh ``python -m pysandboxes.python_sb -c pass`` after the page cache of the interpreter, the provider
binaries and the guest images was evicted (``posix_fadvise(DONTNEED)``, no root needed).
Warm: the same command with the caches left hot, after a first run.
Call: the round trip of a call into a live sandbox.

Run it from a quiet host, outside any sandbox: ``.venv/bin/python scripts/bench_startup.py``.
"""

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

from pysandboxes import sandbox, sandboxes

ROOT = Path(__file__).resolve().parent.parent
PROVIDERS = (
    "none",
    "subprocess",
    "landlock",
    "bwrap",
    "firejail",
    "unshare",
    "gvisor",
    "smolvm",
    "qemu",
    "qemu-microvm",
)
SLOW = {"qemu", "qemu-microvm", "qemu-microvm-tcg"}
CACHED_TREES = (
    ROOT,
    Path(sys.prefix),
    Path(sys.base_prefix),
    Path.home() / ".cache" / "pysandboxes",
    Path.home() / ".cache" / "smolvm",
    Path.home() / ".cache" / "smolvm-image-archives",
    Path("/usr/share/qemu"),
    Path("/usr/lib/qemu"),
)
CACHED_BINARIES = ("bwrap", "firejail", "runsc", "smolvm", "qemu-system-x86_64", "slirp4netns", "iptables", "nsenter")


def profile_text(provider: str) -> str:
    backend = provider.removesuffix("-tcg")
    platform = ""
    if backend.startswith("gvisor-"):
        backend, platform = "gvisor", f"gvisor.platform={provider.removeprefix('gvisor-')}\n"
    exposed = "".join(
        f"expose-ro={p}\n"
        for p in (ROOT, sysconfig.get_paths()["stdlib"], sysconfig.get_paths()["purelib"], sys.base_prefix)
    )
    lines = f"py-sandbox=false\nos-sandbox={backend}\npython-import=*\n{exposed}"
    lines += platform
    if backend == "qemu-microvm":
        lines += "expose-ro=/etc\n"
    lines += f"qemu.use_kvm={'false' if provider.endswith('-tcg') else 'true'}\n"
    return lines


def cached_files() -> list[str]:
    files: list[str] = []
    for tree in CACHED_TREES:
        for base, _, names in os.walk(tree):
            files.extend(os.path.join(base, n) for n in names)
    files.extend(path for name in CACHED_BINARIES if (path := shutil.which(name)))
    image = os.environ.get("PYSANDBOXES_SMOLVM_IMAGE")
    if image:
        files.append(image)
    return files


def evict(files: list[str]) -> None:
    for path in files:
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            continue
        try:
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        finally:
            os.close(fd)


def quiet_host() -> dict[str, float]:
    """Wait until the host is idle, and report the load and free memory the run started with."""
    for _ in range(60):
        load = os.getloadavg()[0]
        if load < 0.6:
            break
        time.sleep(5)
    meminfo = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
    available_gib = int(meminfo["MemAvailable"].split()[0]) / 1048576
    return {"load1": round(os.getloadavg()[0], 2), "mem_available_gib": round(available_gib, 1)}


def run_start(provider: str, profile: Path, files: list[str], timeout: int, *, cold: bool) -> float:
    if cold:
        evict(files)
    quiet_host()
    start = time.perf_counter()
    done = subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", f"--pysandboxes-config={profile}", "-c", "pass"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = time.perf_counter() - start
    if done.returncode != 0:
        raise RuntimeError(f"{provider}: exit {done.returncode}\n{done.stderr[-800:]}")
    return elapsed


@sandbox
def ping() -> int:
    return 1


def call_child(profile: str, calls: int) -> None:
    call_ms: list[float] = []
    with sandboxes(sandboxes_config=profile):
        ping()
        for _ in range(calls):
            begin = time.perf_counter()
            ping()
            call_ms.append((time.perf_counter() - begin) * 1000)
    print(json.dumps(call_ms))


def call_run(provider: str, profile: Path, timeout: int) -> list[float]:
    quiet_host()
    done = subprocess.run(
        [sys.executable, "-m", "scripts.bench_startup", "--child", str(profile)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if done.returncode != 0:
        raise RuntimeError(f"{provider} call: exit {done.returncode}\n{done.stderr[-800:]}")
    return json.loads(done.stdout.strip().splitlines()[-1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", metavar="PROFILE")
    parser.add_argument("--providers", nargs="*", default=list(PROVIDERS))
    parser.add_argument("--cold-runs", type=int, default=5)
    parser.add_argument("--slow-runs", type=int, default=3)
    parser.add_argument("--out", default="bench_startup.json")
    args = parser.parse_args()
    if args.child:
        call_child(args.child, 50)
        return

    files = cached_files()
    results: dict[str, dict] = {"host": quiet_host()}
    tmp = Path.home() / ".cache" / "bench-startup" / "profiles"
    tmp.mkdir(parents=True, exist_ok=True)
    for provider in args.providers:
        slow = provider in SLOW
        runs = args.slow_runs if slow else args.cold_runs
        profile = tmp / f"{provider}.profile"
        profile.write_text(profile_text(provider))
        timeout = 1800 if provider.endswith("-tcg") else 600
        entry: dict = {}
        try:
            cold = [run_start(provider, profile, files, timeout, cold=True) for _ in range(runs)]
            run_start(provider, profile, files, timeout, cold=False)
            warm = [run_start(provider, profile, files, timeout, cold=False) for _ in range(runs)]
        except Exception as error:
            entry["error"] = str(error)
        else:
            entry.update(
                cold=cold,
                cold_median=statistics.median(cold),
                warm=warm,
                warm_median=statistics.median(warm),
            )
            try:
                entry["call_ms_median"] = statistics.median(call_run(provider, profile, timeout))
            except Exception as error:
                entry["call_error"] = str(error)[-300:]
        results[provider] = entry
        print(provider, json.dumps(entry), flush=True)
        Path(args.out).write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
