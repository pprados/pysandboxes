#!/usr/bin/env python3
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Pre-execution hook for coding agents: refuse a shell command that runs Python without python-sb, or python-sb
in learning mode (--learn).

The agent sends the tool call as JSON on stdin. The command is read from `tool_input.command`
(Claude Code, Codex, Gemini CLI, Copilot CLI with `PreToolUse`), `command` (Cursor) or
`toolArgs.command` (Copilot CLI with `preToolUse`). Exit code 2 with the reason on stderr refuses
the command for every one of these agents, and the reason is shown to the model.

This is a guard against a habit, not a barrier: `sh -c "python ..."`, a shebang or a Makefile
still run Python directly.
"""

import json
import re
import shlex
import sys
from pathlib import PurePath

_SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "|&", ";;"}
_PYTHON = re.compile(r"python(\d+(\.\d+)*)?")
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")


def command_of(event: object) -> str | None:
    """Return the shell command of a tool call, whatever the agent, or None."""
    if not isinstance(event, dict):
        return None
    for candidate in (event.get("tool_input"), event, event.get("toolArgs")):
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate)
            except ValueError:
                continue
        if isinstance(candidate, dict) and isinstance(candidate.get("command"), str):
            return candidate["command"]
    return None


def _segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command.replace("\n", ";"), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    segments: list[list[str]] = [[]]
    for token in lexer:
        if token in _SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _program(segment: list[str]) -> str | None:
    words = [word for word in segment if not _ASSIGNMENT.fullmatch(word)]
    launcher = 1 if words[:1] == ["uvx"] else 2 if words[:2] == ["uv", "run"] else 0
    if launcher:
        words = [word for word in words[launcher:] if not word.startswith("-")]
    return PurePath(words[0]).name if words else None


def refusal(command: str) -> str | None:
    """Return why `command` is refused: a direct Python, or python-sb in learning mode. None if allowed."""
    try:
        segments = _segments(command)
    except ValueError:
        return None
    for segment in segments:
        program = _program(segment)
        if program and _PYTHON.fullmatch(program):
            return (
                f"Run Python through python-sb, not {program!r}: replace {program!r} with 'python-sb' "
                "so the rules of .py-sandboxes apply. Do not add --learn, and do not edit .py-sandboxes: "
                "if python-sb refuses an access, report the error."
            )
        if program == "python-sb" and any(word == "--learn" or word.startswith("--learn=") for word in segment):
            return (
                "Do not run python-sb with --learn: the learning mode allows every access and writes the rules "
                "it observes. Run it without --learn, and report the refused access to the user."
            )
    return None


def main() -> int:
    """Read the tool call on stdin and return the exit code of the hook."""
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    command = command_of(event)
    reason = refusal(command) if command else None
    if reason is None:
        return 0
    print(reason, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
