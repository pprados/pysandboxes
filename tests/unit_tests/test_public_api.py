# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""The names `pysandboxes` exports."""

import pysandboxes


def test_guarded_eval_is_exported() -> None:
    assert callable(pysandboxes.guarded_eval)
    assert "guarded_eval" in pysandboxes.__all__


def test_the_eval_exceptions_are_exported() -> None:
    for name in ("EvalSyntaxRejected", "EvalInterrupted", "RuleEvalPermissionError"):
        assert name in pysandboxes.__all__
        assert getattr(pysandboxes, name) is not None


def test_eval_interrupted_is_not_caught_by_sandbox_error() -> None:
    assert not issubclass(pysandboxes.EvalInterrupted, pysandboxes.SandBoxError)
    assert not issubclass(pysandboxes.EvalInterrupted, Exception)


def test_an_unknown_name_still_raises() -> None:
    import pytest  # type: ignore[import-untyped]

    with pytest.raises(AttributeError):
        pysandboxes.no_such_name  # noqa: B018
