# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Replay the mutants of a `make mutation` report against the current tests, with no LLM in the loop.

`scripts/mutation.py --report FILE` stores every mutant with its diff. After tests are written for the
survivors, this script re-applies each stored survivor on a fresh copy of the tree and runs the tests:
a mutant now killed is a gap closed, one still surviving is a missing test or an equivalent mutant.
A diff that no longer applies (the code moved) is reported as stale, not as killed or survived.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mutation import tooling_tests  # noqa: E402


def tracked_files(root: Path) -> list[str]:
    names = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [n for n in names if not n.startswith("samples/") and (root / n).is_file()]


def build_base(root: Path, base: Path) -> None:
    for name in tracked_files(root):
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / name, target)


def patched_file(diff: str) -> str:
    return next(line for line in diff.splitlines() if line.startswith("+++ ")).split(
        "\t"
    )[0][len("+++ b/") :]


def replay(
    mutant: dict,
    base: Path,
    tmp: Path,
    pytest_args: list[str],
    timeout: float,
    slot: int,
) -> tuple[dict, str, str]:
    work = (
        tmp
        / f"w{slot}-{abs(hash((mutant['line'], mutant['operator'], mutant['diff']))) % 10**8}"
    )
    shutil.copytree(base, work, copy_function=os.link)
    target = work / patched_file(mutant["diff"])
    content = target.read_bytes()
    target.unlink()
    target.write_bytes(content)
    patch = "\n".join(mutant["diff"].splitlines()[1:]) + "\n"
    applied = subprocess.run(
        ["patch", "-p1", "-s", "--no-backup-if-mismatch"],
        cwd=work,
        input=patch,
        text=True,
        capture_output=True,
    )
    if applied.returncode:
        shutil.rmtree(work, ignore_errors=True)
        return mutant, "stale", ""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-x",
                "-q",
                "-p",
                "no:cacheprovider",
                *pytest_args,
            ],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        shutil.rmtree(work, ignore_errors=True)
        return mutant, "timeout", ""
    shutil.rmtree(work, ignore_errors=True)
    if result.returncode == 0:
        return mutant, "survived", ""
    failed = [
        line.split(" - ")[0][7:]
        for line in result.stdout.splitlines()
        if line.startswith("FAILED ")
    ]
    crashed = "INTERNALERROR" in result.stdout + result.stderr
    return (
        mutant,
        "suspect" if crashed or not failed else "killed",
        failed[0] if failed else "",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "report",
        type=Path,
        help="JSON written by `scripts/mutation.py --report` (or the triage copy)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="checkout or worktree holding the tests to judge",
    )
    parser.add_argument("--tests", nargs="+", default=["tests/unit_tests"])
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument(
        "--lines", help="only replay these source lines, e.g. 165,182,244"
    )
    parser.add_argument(
        "--out", type=Path, help="write the verdict of every mutant to this JSON file"
    )
    args = parser.parse_args()

    root = args.root.resolve()
    wanted = {int(n) for n in args.lines.split(",")} if args.lines else None
    mutants = [
        m for m in json.loads(args.report.read_text()) if m["outcome"] == "survived"
    ]
    mutants = [m for m in mutants if wanted is None or m["line"] in wanted]
    pytest_args = [*args.tests, *[f"--ignore={f}" for f in tooling_tests(args.tests)]]
    with tempfile.TemporaryDirectory(prefix="pysandboxes-replay-") as tmp_name:
        tmp = Path(tmp_name)
        base = tmp / "base"
        build_base(root, base)
        baseline = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                *pytest_args,
            ],
            cwd=base,
            capture_output=True,
            text=True,
        )
        if baseline.returncode:
            print(
                baseline.stdout[-2500:],
                "\nThe tests fail before any mutation: nothing can be judged.",
                sep="",
            )
            return 2
        with ThreadPoolExecutor(args.jobs) as pool:
            jobs = [
                pool.submit(replay, m, base, tmp, pytest_args, 300.0, i)
                for i, m in enumerate(mutants)
            ]
            verdicts = [job.result() for job in jobs]
    counts: dict[str, int] = {}
    for mutant, verdict, killer in sorted(
        verdicts, key=lambda v: (v[0]["line"], v[0]["operator"])
    ):
        counts[verdict] = counts.get(verdict, 0) + 1
        print(
            f"{verdict:9} {mutant['line']:5} {mutant['operator'].split('/')[-1]:42} {killer.split('::')[-1][:60]}"
        )
    print(json.dumps(counts))
    if args.out:
        args.out.write_text(
            json.dumps(
                [{**m, "verdict": v, "killer": k} for m, v, k in verdicts], indent=1
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
