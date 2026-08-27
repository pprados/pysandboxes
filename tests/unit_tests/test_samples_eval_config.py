# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Every sample that evaluates model output declares its sub-language."""

from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.eval_rules import EvalRules, parse_rules
from pysandboxes.sb_types import ConfigLine

_SAMPLES = (
    "agno-demo",
    "autogen-demo",
    "crewai-demo",
    "google-adk-demo",
    "langchain-demo",
    "langgraph-demo",
    "mcp-server-demo",
    "openai-agents-sdk-demo",
    "pydantic-ai-demo",
    "smolagents-demo",
    "strands-agents-demo",
)

_ROOT = Path(__file__).resolve().parents[2] / "samples"

_REQUIRED = (
    "eval-namespace=closed",
    "eval-syntax=arith, compare",
    "eval-max-iterations=100_000",
    "eval-timeout=2s",
)


@pytest.mark.parametrize("sample", _SAMPLES)
@pytest.mark.parametrize("profile", (".py-sandboxes", ".py-sandboxes-complete"))
def test_the_sample_declares_its_sub_language(sample: str, profile: str) -> None:
    path = _ROOT / sample / profile
    if not path.exists():
        pytest.skip(f"{sample} has no {profile}")
    text = path.read_text()
    for line in _REQUIRED:
        assert line in text, f"{path} is missing {line!r}"


@pytest.mark.parametrize("sample", _SAMPLES)
@pytest.mark.parametrize("profile", (".py-sandboxes", ".py-sandboxes-complete"))
def test_the_declared_lines_parse_into_the_intended_rules(sample: str, profile: str) -> None:
    """Presence of the text is weak; what matters is what it parses into.

    Only the eval- lines are parsed here. A whole-file parse would need to
    resolve the `net=` rules, whose hostnames make this depend on DNS.
    """
    path = _ROOT / sample / profile
    if not path.exists():
        pytest.skip(f"{sample} has no {profile}")
    lines = [
        ConfigLine(text, path, number)
        for number, text in enumerate(path.read_text().splitlines(), start=1)
        if text.strip().startswith("eval-")
    ]
    errors: list[object] = []
    profiles, _ = parse_rules(lines, errors)  # type: ignore[arg-type]
    assert not errors, f"{path}: {errors}"
    # Annotated rather than six `# type: ignore[union-attr]`: ImmutableDict
    # subclasses a tuple pair, so mypy resolves the indexing through
    # tuple.__getitem__ and rejects every field read off the result.
    rules: EvalRules = profiles[""]  # type: ignore[assignment]
    assert rules.declared
    assert rules.namespace == "closed"
    assert rules.timeout == 2.0
    assert rules.max_iterations == 100_000
    # The corpus these tools evaluate is arithmetic and comparisons only,
    # confirmed against the samples' own tests: "14", "2*(3+4)", "112134+1433".
    assert {"BinOp", "Compare"} <= rules.syntax.allow
    # No eval-attribute line: `40 + 2` dispatches int.__add__ inside CPython
    # rather than through an Attribute node, so nothing needs granting.
    assert not rules.attribute.allow


def _own_sources(sample: str) -> list[Path]:
    """Return the sample's own Python files.

    Hidden directories are skipped: each sample carries a `.venv`, and a bare
    rglob walks into it, so the test would otherwise assert on whichever
    third-party packages happen to be installed rather than on the sample.
    """
    return [
        path
        for path in (_ROOT / sample).rglob("*.py")
        if not any(part.startswith(".") for part in path.relative_to(_ROOT).parts)
    ]


@pytest.mark.parametrize("sample", _SAMPLES)
def test_the_sample_dropped_its_noqa(sample: str) -> None:
    """The call is guarded now, not merely hopeful."""
    hits = [path for path in _own_sources(sample) if "S307" in path.read_text()]
    assert not hits, f"{sample} still carries a noqa: S307 in {hits}"
