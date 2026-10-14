# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Mutation testing of one pysandboxes module with cosmic-ray.

cosmic-ray rewrites the module on disk, so every run works on copies of the tracked files, never on
the checkout. Only the function-body lines the tests execute are mutated, split across parallel copies.
A mutant survives when the tests still pass: either a test is missing, or the mutant is equivalent.

Three things keep the equivalent mutants out of the report:
- logging calls (`logger.info(...)`) are never mutated, as no test pins a log message;
- a line carrying `# pragma: no mutate` is skipped; on a compound statement (`if`, `for`, ...) that means its
  header only, not the body;
- `scripts/mutation_equivalents.txt` lists the survivors already judged equivalent, one per line as
  `module | operator | source line`. They are counted apart and not printed.
"""

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EQUIVALENTS = Path(__file__).with_name("mutation_equivalents.txt")
PRAGMA = re.compile(r"#\s*pragma:\s*no mutate\b")
LOGGERS = {"logger", "logging", "log"}
# Operators that mostly produce noise here: arithmetic, unary and constant rewrites.
EXCLUDED_OPERATORS = [
    "core/ReplaceBinaryOperator_.*",
    "core/ReplaceUnaryOperator_.*",
    "core/NumberReplacer",
    "core/VariableReplacer",
    "core/VariableInserter",
]


def tooling_tests(tests: list[str]) -> list[str]:
    """Test files that never import pysandboxes: they check the release tooling, not the module."""
    files = [f for t in tests for f in ((ROOT / t).rglob("test_*.py") if (ROOT / t).is_dir() else [ROOT / t])]
    imports = re.compile(r"^\s*(from|import) pysandboxes\b", re.MULTILINE)
    return sorted(str(f.relative_to(ROOT)) for f in files if not imports.search(f.read_text()))


def is_log_call(statement: ast.stmt) -> bool:
    call = statement.value if isinstance(statement, ast.Expr) else None
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id in LOGGERS
    )


def header_end(statement: ast.stmt) -> int:
    """Last line of the statement itself: for a compound statement, the line before its body."""
    body = getattr(statement, "body", None)
    return body[0].lineno - 1 if body else statement.end_lineno or statement.lineno


def skipped_lines(source: str) -> set[int]:
    """Lines never mutated: logging calls, and statements marked `# pragma: no mutate`."""
    statements = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.stmt)]
    skipped: set[int] = set()
    for statement in statements:
        if is_log_call(statement):
            skipped.update(range(statement.lineno, (statement.end_lineno or statement.lineno) + 1))
    for number, text in enumerate(source.splitlines(), start=1):
        if PRAGMA.search(text):
            marked = [s for s in statements if s.lineno <= number <= header_end(s)]
            if marked:
                innermost = max(marked, key=lambda s: s.lineno)
                skipped.update(range(innermost.lineno, header_end(innermost) + 1))
    return skipped


def body_lines(source: Path) -> set[int]:
    text = source.read_text()
    lines: set[int] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for statement in node.body:
                if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
                    continue
                lines.update(range(statement.lineno, (statement.end_lineno or statement.lineno) + 1))
    return lines - skipped_lines(text)


def known_equivalents() -> set[tuple[str, str, str]]:
    known = set()
    if EQUIVALENTS.exists():
        for line in EQUIVALENTS.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                module, operator, source = (part.strip() for part in line.split("|", 2))
                known.add((module, operator, source))
    return known


def copy_tree(destination: Path) -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    for name in tracked:
        source = ROOT / name
        # The samples are left out, bar their profiles, which the sample-profile tests read.
        if (name.startswith("samples/") and ".py-sandboxes" not in Path(name).name) or not source.is_file():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def pytest_command(tests: list[str], ignored: list[str]) -> list[str]:
    return [sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests] + [
        f"--ignore={f}" for f in ignored
    ]


def run_chunk(work: Path, module: str, lines: list[int], command: list[str], timeout: float) -> list[dict]:
    test_command = " ".join(f"'{part}'" for part in command)
    (work / "cr.toml").write_text(
        "[cosmic-ray]\n"
        f'module-path = "{module}"\ntimeout = {timeout}\nexcluded-modules = []\n'
        f"test-command = {json.dumps(test_command)}\n"
        '[cosmic-ray.distributor]\nname = "local"\n'
        f"[cosmic-ray.filters.operators-filter]\nexclude-operators = {json.dumps(EXCLUDED_OPERATORS)}\n"
        f'[cosmic-ray.filters.line-filter.lines]\n"{module}" = {json.dumps([str(n) for n in lines])}\n'
    )
    bin_dir = Path(sys.executable).parent
    for step in (
        [bin_dir / "cosmic-ray", "init", "cr.toml", "session.sqlite"],
        [bin_dir / "cr-filter-operators", "session.sqlite", "cr.toml"],
        [bin_dir / "cr-filter-lines", "--config", "cr.toml", "session.sqlite"],
        [bin_dir / "cosmic-ray", "exec", "cr.toml", "session.sqlite"],
    ):
        subprocess.run([str(part) for part in step], cwd=work, capture_output=True, check=True)
    dump = subprocess.run(
        [str(bin_dir / "cosmic-ray"), "dump", "session.sqlite"], cwd=work, capture_output=True, text=True, check=True
    ).stdout
    results = []
    for line in dump.splitlines():
        item, result = json.loads(line)
        if result:
            outcome = result["test_outcome"] if result["worker_outcome"] == "normal" else result["worker_outcome"]
            mutation = item["mutations"][0]
            results.append(
                {
                    "line": mutation["start_pos"][0],
                    "operator": mutation["operator_name"],
                    "outcome": outcome,
                    "diff": result.get("diff", ""),
                }
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", help="module to mutate, e.g. pysandboxes/guard_socket.py")
    parser.add_argument("--tests", nargs="+", default=["tests/unit_tests"], help="tests run against each mutant")
    parser.add_argument("--jobs", type=int, default=4, help="parallel copies")
    parser.add_argument("--report", type=Path, help="write every result to this JSON file")
    args = parser.parse_args()

    ignored = tooling_tests(args.tests)
    command = pytest_command(args.tests, ignored)
    with tempfile.TemporaryDirectory(prefix="pysandboxes-mutation-") as tmp:
        base = Path(tmp) / "base"
        copy_tree(base)
        start = time.monotonic()
        baseline = subprocess.run(
            command + ["--cov=pysandboxes", "--cov-report=json:cov.json"], cwd=base, capture_output=True, text=True
        )
        if baseline.returncode != 0:
            print(baseline.stdout[-3000:], baseline.stderr[-3000:], sep="\n")
            print("The tests fail before any mutation: no mutant could be judged.", file=sys.stderr)
            return 2
        timeout = max(60.0, 5 * (time.monotonic() - start))
        executed = json.loads((base / "cov.json").read_text())["files"].get(args.module, {}).get("executed_lines", [])
        source_lines = (base / args.module).read_text().splitlines()
        lines = sorted(set(executed) & body_lines(base / args.module))
        if not lines:
            print(f"The tests execute no function body of {args.module}.", file=sys.stderr)
            return 2
        chunks = [lines[i :: args.jobs] for i in range(args.jobs) if lines[i :: args.jobs]]
        works = []
        for i in range(len(chunks)):
            work = Path(tmp) / f"job{i}"
            shutil.copytree(base, work, ignore=shutil.ignore_patterns("__pycache__", "cov.json"))
            works.append(work)
        print(f"{args.module}: {len(lines)} lines, {len(chunks)} jobs, {timeout:.0f}s timeout per mutant", flush=True)
        with ThreadPoolExecutor(len(chunks)) as pool:
            jobs = [
                pool.submit(run_chunk, work, args.module, chunk, command, timeout)
                for work, chunk in zip(works, chunks, strict=True)
            ]
            results = [result for job in jobs for result in job.result()]
    results.sort(key=lambda r: (r["line"], r["operator"]))
    known = known_equivalents()
    for result in results:
        source = source_lines[result["line"] - 1].strip()
        if result["outcome"] == "survived" and (args.module, result["operator"], source) in known:
            result["outcome"] = "equivalent"
    counts: dict[str, int] = {}
    for result in results:
        counts[result["outcome"]] = counts.get(result["outcome"], 0) + 1
    survivors = [result for result in results if result["outcome"] == "survived"]
    for line in sorted({result["line"] for result in survivors}):
        print(f"{args.module}:{line}  {source_lines[line - 1].strip()}")
        for result in (r for r in survivors if r["line"] == line):
            changed = [
                text for text in result["diff"].splitlines() if text[:1] in "+-" and not text.startswith(("+++", "---"))
            ]
            print(f"  {result['operator']}")
            print("\n".join(f"    {text}" for text in changed))
    print(json.dumps(counts))
    if args.report:
        args.report.write_text(json.dumps(results, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
