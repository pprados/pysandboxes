# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The eval-* rule grammar and the exceptions the guard raises."""

import pickle

from pysandboxes.e import (
    EvalInterrupted,
    EvalSyntaxRejected,
    RuleEvalPermissionError,
    SandBoxError,
    SandboxContextWarning,
)


def test_eval_syntax_rejected_is_a_syntax_error_and_a_sandbox_error() -> None:
    err = EvalSyntaxRejected(
        "1 rule violated in <eval>",
        ["line 1, col 0: 'While' is not allowed"],
        lineno=1,
        offset=0,
        text="while True: pass",
    )
    assert isinstance(err, SyntaxError)
    assert isinstance(err, SandBoxError)
    assert err.violations == ["line 1, col 0: 'While' is not allowed"]
    assert err.lineno == 1
    assert err.text == "while True: pass"


def test_eval_interrupted_is_not_an_exception() -> None:
    """A bare `except Exception:` inside evaluated code must not catch it."""
    err = EvalInterrupted("eval-timeout=5s exhausted")
    assert isinstance(err, BaseException)
    assert not isinstance(err, Exception)
    assert err.reason == "eval-timeout=5s exhausted"


def test_rule_eval_permission_error_names_the_rule_to_add() -> None:
    err = RuleEvalPermissionError("__class__", "eval-magic")
    assert isinstance(err, PermissionError)
    assert isinstance(err, SandBoxError)
    assert "eval-magic=__class__" in str(err)
    assert err.target == "__class__"
    assert err.rule_key == "eval-magic"


def test_rule_eval_permission_error_survives_the_transport() -> None:
    """The sandbox pickles refusals back to the caller."""
    err = pickle.loads(pickle.dumps(RuleEvalPermissionError("split", "eval-attribute")))
    assert err.target == "split"
    assert err.rule_key == "eval-attribute"


def test_sandbox_context_warning_is_a_warning() -> None:
    assert issubclass(SandboxContextWarning, Warning)
