#!/usr/bin/env python3
# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""List the rules a diff adds to or removes from the .py-sandboxes files, riskiest first.

Reads a unified diff on stdin, such as `git diff BASE...HEAD -- '*.py-sandboxes*'`, and prints a Markdown
table, or a JSON list with --json. Standard library only: it runs under python-sb with the rule file of its
skill, and needs neither git nor the network.
"""

import json
import re
import sys
from typing import NamedTuple

# pysandboxes/modules_blacklist.txt and guard_api._WARN_CATEGORIES: tests/unit_tests/test_rules_diff.py keeps
# these two in step with the guards.
DANGEROUS_IMPORTS = frozenset(
    "atexit bdb code codeop cProfile ctypes faulthandler importlib inspect mmap pdb pkgutil posix subprocess "
    "webbrowser".split()
)
DANGEROUS_API = frozenset({"process-exec", "privileges", "native", "dynamic-code", "deserialization"})

_RISK_ORDER = {"high": 0, "medium": 1, "low": 2}
_SECRET = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL", re.IGNORECASE)
_WHOLE_TREE = {"", "~", "$HOME", "${HOME}"}
_OFF = {"false", "0", "no"}


class Change(NamedTuple):
    """One rule line added to or removed from a rule file."""

    file: str
    action: str
    rule: str
    risk: str
    reason: str
    learned_by: str


def grade(rule: str) -> tuple[str, str]:
    """Return the risk of granting `rule`, and why."""
    if rule.startswith("include"):
        return "medium", "pulls in the rules of another file"
    key, _, value = (part.strip() for part in rule.partition("="))
    if key == "python-import":
        names = {name.strip() for name in value.split(",")}
        if "*" in names:
            return "high", "every import allowed"
        if dangerous := sorted(names & DANGEROUS_IMPORTS):
            return "high", f"dangerous module: {', '.join(dangerous)}"
        return "low", "import"
    if key == "python-api":
        action, _, target = value.partition(":")
        if action.upper() != "ALLOW":
            return "low", "denies a call"
        if target == "*":
            return "high", "every sensitive call allowed"
        if target in DANGEROUS_API:
            return "high", f"sensitive category {target}"
        return "medium", "sensitive call allowed"
    if key == "net":
        fields = value.split("|")
        if fields[0].upper() != "ALLOW":
            return "low", "denies a destination"
        network = fields[2] if len(fields) > 2 else "*"
        if network in ("*", "0.0.0.0/0", "::/0"):
            return "high", "any host"
        return "medium", f"network access to {network}"
    if key in ("expose-rw", "expose-ro"):
        writes = key == "expose-rw"
        if value.rstrip("/") in _WHOLE_TREE:
            return ("high" if writes else "medium"), "the whole home or root directory"
        return ("medium", "write access") if writes else ("low", "read access")
    if key in ("env", "set-env"):
        name = value.partition("=")[0]
        if "*" in name:
            return "high", "every environment variable"
        if _SECRET.search(name):
            return "medium", "secret-like variable"
        return "low", "environment variable"
    if key == "learn":
        return ("low", "learning locked off") if value.lower() in _OFF else ("high", "learning mode left on")
    if key in ("py-sandbox", "remote-result-guard"):
        return ("high", f"{key} turned off") if value.lower() in _OFF else ("low", f"{key} on")
    if key == "os-sandbox":
        if value == "none":
            return "high", "no sandbox process, no OS boundary"
        if "subprocess" in value:
            return "medium", "a separate process, with no kernel boundary"
        return "low", f"OS provider {value}"
    if key == "remote-result-mode" and value == "objects":
        return "high", "rebuilds any object in the caller"
    if key == "eval-namespace" and value == "caller":
        return "high", "dynamic code runs unguarded"
    return "medium", "review"


def parse(diff: str) -> list[Change]:
    """Return the rule lines `diff` adds or removes, with the test that learned each added one."""
    found: list[Change] = []
    file = learned_by = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            file, learned_by = line[4:].removeprefix("b/"), ""
            continue
        if line.startswith(("--- ", "@@")) or not line.startswith(("+", "-")):
            continue
        action = "added" if line[0] == "+" else "removed"
        text = line[1:].strip()
        if text.startswith("# Learned by "):
            learned_by = text.removeprefix("# Learned by ") if action == "added" else learned_by
            continue
        rule = re.sub(r"\s+#.*$", "", text)
        if not rule or rule.startswith("#"):
            continue
        if action == "added":
            found.append(Change(file, action, rule, *grade(rule), learned_by))
        else:
            found.append(Change(file, action, rule, "", "narrows the profile", ""))
    return found


def markdown(changes: list[Change]) -> str:
    """Render `changes` as Markdown: added rules riskiest first, then removed ones."""
    if not changes:
        return "No rule change in the .py-sandboxes files."
    added = sorted((c for c in changes if c.action == "added"), key=lambda c: _RISK_ORDER[c.risk])
    removed = [c for c in changes if c.action == "removed"]
    lines = []
    if added:
        lines += ["| Risk | File | Rule | Why | Learned by |", "|---|---|---|---|---|"]
        lines += [f"| {c.risk} | {c.file} | `{c.rule}` | {c.reason} | {c.learned_by} |" for c in added]
    if removed:
        lines += ["", "Removed, which narrows the profile:", ""]
        lines += [f"- {c.file}: `{c.rule}`" for c in removed]
    return "\n".join(lines)


def main() -> int:
    """Read the diff on stdin and print the changes."""
    changes = parse(sys.stdin.read())
    if "--json" in sys.argv[1:]:
        print(json.dumps([c._asdict() for c in changes], indent=2))
    else:
        print(markdown(changes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
