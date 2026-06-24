# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Landlock cannot honour ``ignore=``, and a silent sandbox is the dangerous case.

The ABI knows how to allow a path (``path_beneath``) and nothing else: there is no
deny primitive, so hiding one file inside an exposed directory is inexpressible.
With the Python layer on, ``guard_files`` refuses the path in-process and the rule
still holds. With ``py-sandbox=False`` no layer enforces it, and the profile then
promises a file is hidden while the sandbox reads it -- so that combination, and
only that one, must warn.
"""

import logging
from pathlib import Path

import pytest

from pysandboxes.all_rules import EmptyRules
from pysandboxes.guard_files import IgnoreRule
from pysandboxes.remote.landlock_daemon import _warn_ignore_rules_are_not_enforced
from pysandboxes.sb_types import ConfigLine

_IGNORE_ENV = IgnoreRule(source=".env", config=ConfigLine("ignore=.env", Path(), 0))


def test_an_ignore_rule_without_the_python_layer_warns(caplog: pytest.LogCaptureFixture) -> None:
    rules = EmptyRules._replace(use_py_sandbox=False, file_rules=(_IGNORE_ENV,))

    with caplog.at_level(logging.WARNING):
        _warn_ignore_rules_are_not_enforced(rules)

    assert ".env" in caplog.text, "the warning must name the rule that is not enforced"


def test_the_python_layer_enforces_the_rule_so_nothing_is_reported(
    caplog: pytest.LogCaptureFixture,
) -> None:
    rules = EmptyRules._replace(use_py_sandbox=True, file_rules=(_IGNORE_ENV,))

    with caplog.at_level(logging.WARNING):
        _warn_ignore_rules_are_not_enforced(rules)

    assert not caplog.text, "guard_files still refuses the path, so warning here would be a false alarm"


def test_no_ignore_rule_says_nothing(caplog: pytest.LogCaptureFixture) -> None:
    rules = EmptyRules._replace(use_py_sandbox=False, file_rules=())

    with caplog.at_level(logging.WARNING):
        _warn_ignore_rules_are_not_enforced(rules)

    assert not caplog.text
