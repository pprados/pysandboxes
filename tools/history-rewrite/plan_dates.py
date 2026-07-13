#!/usr/bin/env python3
"""Phase 1: compute the fake date schedule for every commit.

Reads the commit DAG from a git repository and produces a JSON plan mapping each
commit SHA to a new author/committer date, plus a monotone real->fake day map
used later to fix date literals in file names and file contents.

The schedule guarantees, by construction:
  * ancestry: a commit is always scheduled after every one of its parents;
  * strict monotonicity along the emitted sequence;
  * every date falls on a business day, outside the excluded month, inside the
    configured working hours, with the correct Europe/Paris UTC offset (DST);
  * the gap before a commit reflects how much work it represents, so a large
    diff is not committed minutes after the previous one;
  * the shape of the real history survives: bursts stay bursts, quiet stretches
    stay quiet.

The last two points come from a single blended weight per commit. Each commit is
given a *work duration*, and its timestamp is placed at the end of that duration
on the working-hours axis; when a duration does not fit in what is left of a
day, the timestamp naturally rolls over to the next business day. The weight
blends two signals:

  volume  insertions + deletions, which makes the gap proportional to the amount
          of work the commit contains;
  shape   the real elapsed time since the previous commit, which preserves the
          genuine idle stretches that produce no volume at all (holidays).

`--shape-weight` is the share given to the second signal.
"""

import argparse
import bisect
import heapq
import json
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")


class Commit:
    __slots__ = ("sha", "parents", "author_epoch", "volume")

    def __init__(self, sha: str, parents: list[str], author_epoch: int) -> None:
        self.sha = sha
        self.parents = parents
        self.author_epoch = author_epoch
        self.volume = 0


def read_dag(repo: str, refs: list[str]) -> dict[str, Commit]:
    """Load the commit DAG reachable from `refs`, with per-commit diff volume.

    `--numstat` emits nothing for merge commits, which is what we want: a merge
    is cheap, and it will simply fall back to the minimum gap.
    """
    out = subprocess.run(
        ["git", "-C", repo, "log", "--format=@%H|%P|%at", "--numstat", *refs],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    commits: dict[str, Commit] = {}
    current: Commit | None = None
    for line in out.splitlines():
        if line.startswith("@"):
            sha, parents, at = line[1:].split("|")
            current = Commit(sha, parents.split() if parents else [], int(at))
            commits[sha] = current
            continue
        if not line.strip() or current is None:
            continue
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        added, removed = fields[0], fields[1]
        # "-" marks a binary file: count it as a modest fixed volume.
        current.volume += 50 if added == "-" else int(added) + int(removed)
    return commits


def topo_order(commits: dict[str, Commit]) -> list[Commit]:
    """Kahn topological sort, ties broken by the real author date.

    This is deliberately not `git rev-list --topo-order`: that command groups a
    branch's commits together, which would serialise work that really happened in
    parallel. Breaking ties on the real date instead preserves the interleaving
    between branches as far as ancestry allows.
    """
    children: dict[str, list[str]] = {sha: [] for sha in commits}
    pending: dict[str, int] = {}
    for sha, commit in commits.items():
        known = [p for p in commit.parents if p in commits]
        pending[sha] = len(known)
        for parent in known:
            children[parent].append(sha)

    heap = [(c.author_epoch, c.sha) for c in commits.values() if pending[c.sha] == 0]
    heapq.heapify(heap)

    order: list[Commit] = []
    while heap:
        _, sha = heapq.heappop(heap)
        order.append(commits[sha])
        for child in children[sha]:
            pending[child] -= 1
            if pending[child] == 0:
                heapq.heappush(heap, (commits[child].author_epoch, child))

    if len(order) != len(commits):
        raise SystemExit(f"cycle or missing parent: ordered {len(order)} of {len(commits)}")
    return order


def business_days(start: date, end: date, skip_month: int | None) -> list[date]:
    """Business days in [start, end], excluding weekends and `skip_month`."""
    days: list[date] = []
    day = start
    while day <= end:
        if day.weekday() < 5 and day.month != skip_month:
            days.append(day)
        day += timedelta(days=1)
    return days


class WorkCalendar:
    """A flat, seconds-addressable timeline of working hours.

    Position 0 is `day_start` on the first business day; each day holds
    `seconds_per_day` seconds, and positions beyond that roll over to the next
    business day. A commit whose work duration does not fit in what remains of a
    day therefore lands the next morning, with no special casing.
    """

    def __init__(self, days: list[date], day_start: time, day_end: time) -> None:
        if not days:
            raise SystemExit("no business day available in the target window")
        self.days = days
        self.day_start = day_start
        self.seconds_per_day = (
            datetime.combine(date(2000, 1, 1), day_end) - datetime.combine(date(2000, 1, 1), day_start)
        ).seconds
        if self.seconds_per_day <= 0:
            raise SystemExit("day-end must be after day-start")
        self.capacity = self.seconds_per_day * len(days)

    def at(self, position: int) -> datetime:
        position = max(0, min(position, self.capacity - 1))
        day_index, offset = divmod(position, self.seconds_per_day)
        naive = datetime.combine(self.days[day_index], self.day_start) + timedelta(seconds=offset)
        return naive.replace(tzinfo=TZ)


def monotone_real_dates(order: list[Commit]) -> list[int]:
    """Real author dates forced non-decreasing along the emitted order.

    Rebases and cherry-picks routinely produce a child older than its parent, so
    the raw dates cannot be used as a position source directly.
    """
    series: list[int] = []
    running = order[0].author_epoch
    for commit in order:
        running = max(running, commit.author_epoch)
        series.append(running)
    return series


def work_durations(
    order: list[Commit],
    real_dates: list[int],
    capacity: int,
    min_gap: int,
    max_gap: int,
    shape_weight: float,
) -> list[int]:
    """Per-commit work duration, blending diff volume and real elapsed time."""
    volumes = [float(c.volume) for c in order]
    gaps = [0.0] + [float(max(0, real_dates[i] - real_dates[i - 1])) for i in range(1, len(order))]

    volume_total = sum(volumes)
    gap_total = sum(gaps)
    if volume_total == 0 and gap_total == 0:
        weights = [1.0] * len(order)
    else:
        weights = []
        for volume, gap in zip(volumes, gaps):
            volume_share = 0.0 if volume_total == 0 else volume / volume_total
            gap_share = 0.0 if gap_total == 0 else gap / gap_total
            weights.append((1.0 - shape_weight) * volume_share + shape_weight * gap_share)

    weight_total = sum(weights) or 1.0
    durations = [max(min_gap, min(max_gap, int(w / weight_total * capacity))) for w in weights]

    # Clamping breaks the budget in both directions; rescale the slack that is
    # still free to move (anything strictly above the floor) until it fits.
    total = sum(durations)
    if total > capacity:
        movable = sum(d - min_gap for d in durations)
        if movable <= 0:
            raise SystemExit(
                f"target window too small: {len(order)} commits need at least "
                f"{min_gap * len(order)}s but only {capacity}s are available"
            )
        scale = (capacity - min_gap * len(order)) / movable
        durations = [min_gap + int((d - min_gap) * scale) for d in durations]
    return durations


def build_plan(
    order: list[Commit],
    calendar: WorkCalendar,
    min_gap: int,
    max_gap: int,
    shape_weight: float,
) -> tuple[dict[str, dict[str, str]], list[tuple[int, int]], list[int]]:
    """Place every commit at the end of its work duration on the calendar."""
    real_dates = monotone_real_dates(order)
    durations = work_durations(
        order, real_dates, calendar.capacity, min_gap, max_gap, shape_weight
    )

    plan: dict[str, dict[str, str]] = {}
    anchors: list[tuple[int, int]] = []
    position = 0
    previous = -1
    for index, commit in enumerate(order):
        position += durations[index]
        position = max(position, previous + min_gap)
        previous = position

        moment = calendar.at(position)
        stamp = git_date(moment)
        plan[commit.sha] = {"author_date": stamp, "committer_date": stamp}
        anchors.append((real_dates[index], int(moment.timestamp())))

    return plan, anchors, durations


def git_date(moment: datetime) -> str:
    """Format as git stores it: epoch seconds plus the local UTC offset."""
    offset = moment.utcoffset() or timedelta(0)
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    total = abs(total)
    return f"{int(moment.timestamp())} {sign}{total // 3600:02d}{(total % 3600) // 60:02d}"


def build_day_map(anchors: list[tuple[int, int]]) -> dict[str, str]:
    """Monotone real-day -> fake-day map, for date literals in names and contents.

    Interpolates between the scheduled commits, so a date written inside a file
    moves consistently with the commit that wrote it.
    """
    reals = [a[0] for a in anchors]
    fakes = [a[1] for a in anchors]
    first_real = datetime.fromtimestamp(reals[0], TZ).date()
    last_real = datetime.fromtimestamp(reals[-1], TZ).date()

    mapping: dict[str, str] = {}
    day = first_real
    while day <= last_real:
        epoch = int(datetime.combine(day, time(12, 0), tzinfo=TZ).timestamp())
        index = min(bisect.bisect_left(reals, epoch), len(fakes) - 1)
        mapping[day.isoformat()] = datetime.fromtimestamp(fakes[index], TZ).date().isoformat()
        day += timedelta(days=1)
    return mapping


def summarise(order: list[Commit], durations: list[int], anchors: list[tuple[int, int]]) -> None:
    per_day: dict[str, int] = {}
    for _, fake in anchors:
        key = datetime.fromtimestamp(fake, TZ).strftime("%Y-%m-%d")
        per_day[key] = per_day.get(key, 0) + 1

    biggest = max(range(len(order)), key=lambda i: order[i].volume)
    print(f"{len(order)} commits scheduled over {len(per_day)} active business days")
    print(f"window   : {datetime.fromtimestamp(anchors[0][1], TZ):%Y-%m-%d %H:%M}"
          f" -> {datetime.fromtimestamp(anchors[-1][1], TZ):%Y-%m-%d %H:%M}")
    print(f"gap       : min {min(durations)}s, median {sorted(durations)[len(durations) // 2]}s,"
          f" max {max(durations)}s")
    print(f"busiest   : {max(per_day.values())} commits in a day")
    print(f"largest   : {order[biggest].sha[:12]} ({order[biggest].volume} lines,"
          f" gap {durations[biggest]}s)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="repository to read the DAG from")
    parser.add_argument("--refs", nargs="+", default=["--all"], help="refs delimiting the commit set")
    parser.add_argument("--start", required=True, help="first day of the target window (YYYY-MM-DD)")
    parser.add_argument("--end", required=True, help="last day of the target window (YYYY-MM-DD)")
    parser.add_argument("--skip-month", type=int, default=8, help="month to leave empty (0 to disable)")
    parser.add_argument("--day-start", default="08:00", help="start of the working day")
    parser.add_argument("--day-end", default="18:30", help="end of the working day")
    parser.add_argument("--min-gap", type=int, default=300, help="minimum seconds between two commits")
    parser.add_argument(
        "--max-gap",
        type=int,
        default=0,
        help="maximum seconds attributed to one commit (0 means one full working day)",
    )
    parser.add_argument(
        "--shape-weight",
        type=float,
        default=0.5,
        help="share of the gap driven by the real elapsed time rather than the diff volume",
    )
    parser.add_argument("--out", required=True, help="where to write the JSON plan")
    args = parser.parse_args()

    if not 0.0 <= args.shape_weight <= 1.0:
        raise SystemExit("--shape-weight must be between 0 and 1")

    commits = read_dag(args.repo, args.refs)
    if not commits:
        raise SystemExit("no commit found")
    order = topo_order(commits)

    days = business_days(
        date.fromisoformat(args.start),
        date.fromisoformat(args.end),
        args.skip_month or None,
    )
    calendar = WorkCalendar(days, time.fromisoformat(args.day_start), time.fromisoformat(args.day_end))
    max_gap = args.max_gap or calendar.seconds_per_day
    plan, anchors, durations = build_plan(order, calendar, args.min_gap, max_gap, args.shape_weight)

    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "commits": plan,
                "order": [c.sha for c in order],
                "day_map": build_day_map(anchors),
            },
            handle,
            indent=1,
        )

    summarise(order, durations, anchors)
    print(f"plan written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
