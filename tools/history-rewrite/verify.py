#!/usr/bin/env python3
"""Verification harness for the history rewrite.

Two independent modes:

  plan   checks the schedule produced by plan_dates.py, before anything is
         rewritten: ancestry, strict monotonicity, calendar constraints, and the
         monthly distribution (so the burst/quiet shape can be eyeballed);

  repo   compares a rewritten repository against the original one: identical
         trees per ref, identical commit count, identical branch and tag sets,
         and every commit dated after all of its parents.

Tree equality is the strongest check: it proves only metadata moved.
"""

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, time
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")


def git(repo: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", repo, *args], capture_output=True, text=True, check=True
    ).stdout


def parents_of(repo: str, refs: list[str]) -> dict[str, list[str]]:
    out = git(repo, "log", "--format=%H|%P", *refs)
    table: dict[str, list[str]] = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, raw = line.split("|")
        table[sha] = raw.split() if raw else []
    return table


def commit_dates(repo: str, refs: list[str]) -> dict[str, int]:
    out = git(repo, "log", "--format=%H|%at", *refs)
    table: dict[str, int] = {}
    for line in out.splitlines():
        if not line.strip():
            continue
        sha, at = line.split("|")
        table[sha] = int(at)
    return table


def refs_of(repo: str, namespace: str) -> set[str]:
    out = git(repo, "for-each-ref", "--format=%(refname:short)", namespace)
    return {line.strip() for line in out.splitlines() if line.strip()}


def check_calendar(epoch: int, day_start: time, day_end: time, skip_month: int | None) -> str | None:
    moment = datetime.fromtimestamp(epoch, TZ)
    if moment.weekday() >= 5:
        return "weekend"
    if skip_month and moment.month == skip_month:
        return "excluded month"
    if not (day_start <= moment.time() <= day_end):
        return "outside working hours"
    return None


def verify_plan(args: argparse.Namespace) -> int:
    with open(args.plan, encoding="utf-8") as handle:
        payload = json.load(handle)
    plan = payload["commits"]
    order = payload["order"]
    parents = parents_of(args.repo, args.refs)

    def epoch(sha: str) -> int:
        return int(plan[sha]["author_date"].split()[0])

    failures: list[str] = []

    missing = [sha for sha in parents if sha not in plan]
    if missing:
        failures.append(f"{len(missing)} commits absent from the plan (e.g. {missing[0]})")
    if len(order) != len(parents):
        failures.append(f"plan covers {len(order)} commits, repository has {len(parents)}")

    ancestry = [
        (sha, parent)
        for sha in order
        for parent in parents.get(sha, [])
        if parent in plan and epoch(sha) <= epoch(parent)
    ]
    if ancestry:
        failures.append(f"{len(ancestry)} commits not strictly after a parent (e.g. {ancestry[0][0][:12]})")

    sequence = [epoch(sha) for sha in order]
    regressions = sum(1 for before, after in zip(sequence, sequence[1:]) if after <= before)
    if regressions:
        failures.append(f"{regressions} non-increasing steps in the emitted order")

    day_start = time.fromisoformat(args.day_start)
    day_end = time.fromisoformat(args.day_end)
    calendar = [
        (sha, reason)
        for sha in order
        if (reason := check_calendar(epoch(sha), day_start, day_end, args.skip_month or None))
    ]
    if calendar:
        counts = Counter(reason for _, reason in calendar)
        failures.append(f"{len(calendar)} commits break the calendar: {dict(counts)}")

    print(f"commits      : {len(order)}")
    print(f"span         : {datetime.fromtimestamp(sequence[0], TZ):%Y-%m-%d %H:%M}"
          f" -> {datetime.fromtimestamp(sequence[-1], TZ):%Y-%m-%d %H:%M}")
    print("distribution :")
    per_month = Counter(datetime.fromtimestamp(e, TZ).strftime("%Y-%m") for e in sequence)
    for month in sorted(per_month):
        print(f"    {month}  {per_month[month]:4d}  {'#' * (per_month[month] // 2)}")

    return report(failures)


def verify_repo(args: argparse.Namespace) -> int:
    failures: list[str] = []

    original_branches = refs_of(args.original, "refs/heads/")
    rewritten_branches = refs_of(args.repo, "refs/heads/")
    if original_branches != rewritten_branches:
        only_before = original_branches - rewritten_branches
        only_after = rewritten_branches - original_branches
        failures.append(f"branch sets differ (removed: {sorted(only_before)}, added: {sorted(only_after)})")

    original_tags = refs_of(args.original, "refs/tags/")
    rewritten_tags = refs_of(args.repo, "refs/tags/")
    if original_tags != rewritten_tags:
        failures.append(f"tag sets differ (before: {sorted(original_tags)}, after: {sorted(rewritten_tags)})")

    before_count = len(commit_dates(args.original, args.refs))
    after_count = len(commit_dates(args.repo, args.refs))
    if before_count != after_count:
        failures.append(f"commit count changed: {before_count} -> {after_count}")

    for branch in sorted(original_branches & rewritten_branches):
        before_tree = git(args.original, "rev-parse", f"{branch}^{{tree}}").strip()
        after_tree = git(args.repo, "rev-parse", f"{branch}^{{tree}}").strip()
        if before_tree != after_tree and not args.expect_tree_changes:
            failures.append(f"{branch}: tree differs ({before_tree[:12]} -> {after_tree[:12]})")

    parents = parents_of(args.repo, args.refs)
    dates = commit_dates(args.repo, args.refs)
    ancestry = [
        sha
        for sha, plist in parents.items()
        for parent in plist
        if parent in dates and dates[sha] <= dates[parent]
    ]
    if ancestry:
        failures.append(f"{len(ancestry)} rewritten commits not strictly after a parent")

    day_start = time.fromisoformat(args.day_start)
    day_end = time.fromisoformat(args.day_end)
    calendar = [
        sha for sha, epoch in dates.items()
        if check_calendar(epoch, day_start, day_end, args.skip_month or None)
    ]
    if calendar:
        failures.append(f"{len(calendar)} rewritten commits break the calendar")

    print(f"commits      : {after_count}")
    print(f"branches     : {len(rewritten_branches)}")
    print(f"tags         : {len(rewritten_tags)}")

    return report(failures)


def report(failures: list[str]) -> int:
    print()
    if failures:
        print("FAILED")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("OK - all checks passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["plan", "repo"])
    parser.add_argument("--repo", required=True, help="repository under test")
    parser.add_argument("--original", help="reference repository (repo mode)")
    parser.add_argument("--plan", help="JSON plan to verify (plan mode)")
    parser.add_argument("--refs", nargs="+", default=["--branches", "--tags"])
    parser.add_argument("--skip-month", type=int, default=8)
    parser.add_argument("--day-start", default="08:00")
    parser.add_argument("--day-end", default="18:30")
    parser.add_argument(
        "--expect-tree-changes",
        action="store_true",
        help="tolerate tree differences (set once date literals in files are rewritten)",
    )
    args = parser.parse_args()

    if args.mode == "plan":
        if not args.plan:
            raise SystemExit("--plan is required in plan mode")
        return verify_plan(args)
    if not args.original:
        raise SystemExit("--original is required in repo mode")
    return verify_repo(args)


if __name__ == "__main__":
    sys.exit(main())
