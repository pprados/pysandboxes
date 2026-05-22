# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Behaviour of the guard_api layer."""

from pathlib import Path

import pytest

import pysandboxes
from pysandboxes.e import RuleApiPermissionError, SandBoxError
from pysandboxes.guard_api import ApiRule, parse_rules
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine


def test_exception_is_a_permission_error() -> None:
    """User code catching PermissionError keeps working."""
    err = RuleApiPermissionError("os.system", "process-exec")
    assert isinstance(err, PermissionError)
    assert isinstance(err, SandBoxError)


def test_exception_message_tells_how_to_unblock() -> None:
    err = RuleApiPermissionError("os.system", "process-exec")
    message = str(err)
    assert "os.system" in message
    assert "process-exec" in message
    assert "python-api=ALLOW:os.system" in message
    assert "python-api=ALLOW:process-exec" in message


def test_exception_is_exported() -> None:
    assert pysandboxes.RuleApiPermissionError is RuleApiPermissionError
    assert "RuleApiPermissionError" in pysandboxes.__all__


def test_no_dead_name_in_all() -> None:
    """__all__ must not advertise names that do not exist."""
    for name in pysandboxes.__all__:
        assert getattr(pysandboxes, name, None) is not None, name


def _parse(*rules: str) -> tuple[tuple[ApiRule, ...], list[ErrorMsg]]:
    errors: list[ErrorMsg] = []
    lines = [ConfigLine(r, Path("p"), i) for i, r in enumerate(rules)]
    parsed, remaining = parse_rules(lines, errors)
    assert not remaining, "python-api= lines must be consumed"
    return parsed, errors


def test_allow_a_category() -> None:
    parsed, errors = _parse("python-api=ALLOW:threads")
    assert not errors
    assert parsed[0].allow is True
    assert parsed[0].target == "threads"
    assert parsed[0].is_category is True


def test_allow_a_function() -> None:
    parsed, errors = _parse("python-api=ALLOW:os.system")
    assert not errors
    assert parsed[0].target == "os.system"
    assert parsed[0].is_category is False


def test_deny_and_several_targets_on_one_line() -> None:
    parsed, errors = _parse("python-api=DENY:threads, os.system")
    assert not errors
    assert [r.target for r in parsed] == ["threads", "os.system"]
    assert all(r.allow is False for r in parsed)


def test_rules_accumulate_across_lines() -> None:
    parsed, errors = _parse(
        "python-api=ALLOW:threads",
        "python-api=DENY:threading.settrace",
    )
    assert not errors
    assert len(parsed) == 2


def test_wildcards() -> None:
    parsed, errors = _parse("python-api=ALLOW:*", "python-api=DENY:*")
    assert not errors
    assert [r.target for r in parsed] == ["*", "*"]


def test_other_directives_are_returned_untouched() -> None:
    errors: list[ErrorMsg] = []
    lines = [ConfigLine("expose-ro=.", Path("p"), 0)]
    parsed, remaining = parse_rules(lines, errors)
    assert not parsed
    assert not errors
    assert remaining == lines


@pytest.mark.parametrize(
    "rule",
    [
        "python-api=ALLOW:threadz",
        "python-api=ALLOW:os.systemm",
        "python-api=ALLOW:os.no_such_function",
        "python-api=threads",
        "python-api=PERMIT:threads",
        "python-api=ALLOW:threads,DENY:os.system",
        "python-api=ALLOW:",
        "python-api=ALLOW:threads,",
        "python-api=",
    ],
)
def test_rejected_syntax(rule: str) -> None:
    parsed, errors = _parse(rule)
    assert errors, f"{rule!r} should be rejected"
    assert not parsed


def test_error_carries_provenance() -> None:
    _, errors = _parse("python-api=ALLOW:threadz")
    message, path, line = errors[0]
    assert path == Path("p")
    assert line == 0
    assert "threadz" in message
