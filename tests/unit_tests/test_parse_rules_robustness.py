# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
from pathlib import Path
from typing import Any, Callable

import pytest  # type: ignore[import-untyped]
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pysandboxes import eval_rules, guard_api, guard_envs, guard_files, guard_import, guard_socket
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine, ConfigLines

PATH = Path("fuzz.profile")

PREFIXES = {
    "eval": [
        "eval-call=",
        "eval-import=",
        "eval-syntax=",
        "eval-attribute=",
        "eval-magic=",
        "eval-max-nodes=",
        "eval-max-alloc=",
        "eval-timeout=",
        "eval-namespace=",
        "eval-bogus=",
    ],
    "api": ["python-api=", "python-api=ALLOW:", "python-api=DENY:"],
    "import": ["python-import=", "python-import=ALLOW:", "python-import=DENY:"],
    "files": ["expose-ro=", "expose-rw=", "ignore=", "expose-ro=${HOME}/"],
    "socket": ["net=", "net=ALLOW:", "net=DENY:", "net=ALLOW:*:", "net=ALLOW:127.0.0.1:"],
    "envs": ["env=", "env=ALLOW:", "env=DENY:", "env=A=", "env=ALLOW:A*"],
}

tails = st.text(alphabet=st.characters(blacklist_categories=("Cs", "Cc")), max_size=14)


def _lines(group: str) -> st.SearchStrategy[ConfigLines]:
    one = st.builds(lambda p, t: p + t, st.sampled_from(PREFIXES[group]), tails)
    return st.lists(one, min_size=1, max_size=4).map(
        lambda rules: [ConfigLine(rule, PATH, n) for n, rule in enumerate(rules, start=1)]
    )


def _call(group: str) -> Callable[[ConfigLines, list[ErrorMsg]], Any]:
    if group == "eval":
        return lambda lines, errors: eval_rules.parse_rules(lines, errors)
    if group == "api":
        return lambda lines, errors: guard_api.parse_rules(lines, errors)
    if group == "import":
        return lambda lines, errors: guard_import.parse_rules(lines, errors)
    if group == "files":
        return lambda lines, errors: guard_files.parse_rules(lines, errors)
    if group == "socket":
        return lambda lines, errors: guard_socket.parse_rules(lines, errors)
    return lambda lines, errors: guard_envs.parse_rules(lines, {}, errors)


def _others(group: str, result: Any) -> ConfigLines:
    return result[2] if group == "envs" else result[1] if group != "socket" else result[1]


@pytest.mark.parametrize("group", sorted(PREFIXES))
def test_a_rule_the_parser_cannot_use_is_reported_not_raised(group: str) -> None:
    @settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(_lines(group))
    def check(lines: ConfigLines) -> None:
        errors: list[ErrorMsg] = []
        result = _call(group)(lines, errors)
        assert set(_others(group, result)) <= set(lines)

    check()


def test_the_properties_have_teeth() -> None:
    """Negative control: a parser that raises, or that invents a line, would be caught by the check above."""
    lines = [ConfigLine("eval-max-alloc=infMB", PATH, 1)]
    with pytest.raises(OverflowError):
        eval_rules.parse_scalar.__wrapped__("eval-max-alloc", "infMB")  # type: ignore[attr-defined]
    assert set([ConfigLine("invented", PATH, 9)]) - set(lines)
