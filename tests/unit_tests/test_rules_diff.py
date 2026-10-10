# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from pysandboxes import guard_api

SCRIPT = Path(__file__).parents[2] / "skills" / "pysandboxes-review-rules" / "scripts" / "rules_diff.py"
BLACKLIST = Path(__file__).parents[2] / "pysandboxes" / "modules_blacklist.txt"


def run(diff: str, *args: str) -> str:
    done = subprocess.run([sys.executable, str(SCRIPT), *args], input=diff, capture_output=True, text=True, check=True)
    return done.stdout


def diff_adding(*lines: str, file: str = ".py-sandboxes") -> str:
    body = "\n".join(f"+{line}" for line in lines)
    return f"--- a/{file}\n+++ b/{file}\n@@ -1,0 +1,{len(lines)} @@\n{body}\n"


def changes(diff: str) -> list[dict[str, str]]:
    return json.loads(run(diff, "--json"))


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rules_diff", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("rule", "risk"),
    [
        ("python-import=json, csv", "low"),
        ("python-import=subprocess", "high"),
        ("python-import=*", "high"),
        ("python-api=ALLOW:process-exec", "high"),
        ("python-api=ALLOW:*", "high"),
        ("python-api=ALLOW:threads", "medium"),
        ("python-api=DENY:os.system", "low"),
        ("net=ALLOW|*|*|*|*", "high"),
        ("net=ALLOW|tcp|api.example.com|443|OUT", "medium"),
        ("expose-ro=./data", "low"),
        ("expose-rw=./out", "medium"),
        ("expose-rw=~", "high"),
        ("env=LANG=${LANG}", "low"),
        ("env=OPENAI_API_KEY=${OPENAI_API_KEY}", "medium"),
        ("env=*=${*}", "high"),
        ("learn=.py-sandboxes", "high"),
        ("learn=false", "low"),
        ("py-sandbox=false", "high"),
        ("py-sandbox=true", "low"),
        ("os-sandbox=none", "high"),
        ("os-sandbox=${OS_SANDBOX:-subprocess}", "medium"),
        ("os-sandbox=bwrap", "low"),
        ("remote-result-mode=objects", "high"),
        ('include "other.py-sandboxes"', "medium"),
    ],
)
def test_each_added_rule_is_graded(rule: str, risk: str) -> None:
    [change] = changes(diff_adding(rule))
    assert (change["action"], change["rule"], change["risk"]) == ("added", rule, risk)


def test_comments_and_blank_lines_are_not_rules() -> None:
    assert changes(diff_adding("# Add rules (2026/10/07 at 14:00)", "", "# Standard Python")) == []


def test_a_removed_rule_narrows_the_profile() -> None:
    diff = "--- a/.py-sandboxes\n+++ b/.py-sandboxes\n@@ -1,1 +0,0 @@\n-python-import=csv\n"
    [change] = changes(diff)
    assert (change["action"], change["rule"]) == ("removed", "python-import=csv")


def test_a_rule_names_the_test_that_learned_it() -> None:
    [change] = changes(
        diff_adding(
            "# Learned by tests/test_feature.py::test_export",
            "# Add rules (2026/10/07 at 14:00)",
            "python-import=_csv, csv",
        )
    )
    assert change["learned_by"] == "tests/test_feature.py::test_export"


def test_the_table_lists_the_riskiest_rule_first() -> None:
    table = run(diff_adding("python-import=csv", "python-api=ALLOW:process-exec"))
    assert table.index("process-exec") < table.index("csv")
    assert "| high |" in table


def test_no_rule_change_says_so() -> None:
    assert run("").strip() == "No rule change in the .py-sandboxes files."


def test_the_dangerous_imports_are_those_of_the_import_guard() -> None:
    assert load_script().DANGEROUS_IMPORTS == frozenset(BLACKLIST.read_text().split())


def test_the_dangerous_api_categories_are_those_of_the_api_guard() -> None:
    assert load_script().DANGEROUS_API == frozenset(guard_api._WARN_CATEGORIES)
