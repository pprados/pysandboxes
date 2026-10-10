# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Run ``make format`` on Python files changed in the current worktree."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

_SAFE_PATH = re.compile(r"[A-Za-z0-9_./+-]+\Z")
_FORMATTABLE_SUFFIXES = {".ipynb", ".py"}


def _git_paths(root: Path, *arguments: str) -> set[str]:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {os.fsdecode(path) for path in result.stdout.split(b"\0") if path}


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return Path(os.fsdecode(result.stdout.rstrip(b"\n")))


def _format_paths(root: Path) -> list[str]:
    changed = _git_paths(root, "diff", "--name-only", "-z", "--diff-filter=ACMRT", "HEAD", "--")
    changed.update(_git_paths(root, "ls-files", "--others", "--exclude-standard", "-z"))

    result: list[str] = []
    root_resolved = root.resolve()
    for path in sorted(changed):
        relative_path = Path(path)
        if relative_path.suffix not in _FORMATTABLE_SUFFIXES:
            continue

        candidate = root / relative_path
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            candidate.resolve().relative_to(root_resolved)
        except (OSError, ValueError):
            continue

        if not _SAFE_PATH.fullmatch(path) or any(part.startswith("-") for part in relative_path.parts):
            raise ValueError(f"Cannot safely pass this path to make format: {path!r}")
        result.append(path)
    return result


def main() -> int:
    try:
        root = _repo_root()
        paths = _format_paths(root)
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        print(f"Codex format hook failed: {error}", file=sys.stderr)
        return 1

    if not paths:
        return 0

    result = subprocess.run(["make", "format", f"PYTHON_FILES={' '.join(paths)}"], cwd=root)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
