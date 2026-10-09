# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The conftest.py that learns rules from tests is printed twice: keep the copies identical."""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
FAQ = ROOT / "wiki" / "faq.md"
SKILL = ROOT / "skills" / "skills" / "pysandboxes-rules-from-tests" / "SKILL.md"


def conftest_block(page: Path) -> str:
    [block] = re.findall(r"```python\n(# conftest\.py\n.*?)```", page.read_text(), re.DOTALL)
    return block


def test_the_faq_and_the_skill_print_the_same_conftest() -> None:
    assert conftest_block(FAQ) == conftest_block(SKILL)


def test_the_printed_conftest_is_valid_python() -> None:
    ast.parse(conftest_block(SKILL))
