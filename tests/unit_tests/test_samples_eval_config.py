# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Every sample that evaluates model output declares its sub-language."""

import sys
from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.eval_rules import EvalRules, parse_rules
from pysandboxes.sb_types import ConfigLine

_STANDARD_SAMPLES = (
    "agno-demo",
    "autogen-demo",
    "crewai-demo",
    "google-adk-demo",
    "langchain-demo",
    "langgraph-demo",
    "openai-agents-sdk-demo",
    "pydantic-ai-demo",
    "smolagents-demo",
    "strands-agents-demo",
)

_SAMPLES = (*_STANDARD_SAMPLES, "mcp-server-demo")

# The MCP server sample keeps one profile per mode next to its server, besides the one at its root.
_PROFILES = (
    *((sample, name) for sample in _STANDARD_SAMPLES for name in (".py-sandboxes", ".py-sandboxes-complete")),
    ("mcp-server-demo", ".py-sandboxes"),
    ("mcp-server-demo", "mcp_server/.py-sandboxes"),
    ("mcp-server-demo", "mcp_server/.py-sandboxes-complete"),
)

_ROOT = Path(__file__).resolve().parents[2] / "samples"

_REQUIRED = (
    "eval-namespace=closed",
    "eval-syntax=arith, compare",
    "eval-max-iterations=100_000",
    "eval-timeout=2s",
)


@pytest.mark.skipif(sys.platform != "linux", reason="MicroVM is a Linux provider")
@pytest.mark.parametrize("requested", ["false", "true"])
def test_the_mcp_profile_honors_the_requested_qemu_acceleration(requested: str) -> None:
    from pysandboxes.py_sandbox import load_and_parse_config

    rules = load_and_parse_config(
        config_path=_ROOT / "mcp-server-demo/mcp_server/unix.profile",
        envs={"QEMU_USE_KVM": requested},
        os_sandbox="qemu-microvm",
    )

    assert rules.os_sandbox_params["use_kvm"] == requested


def test_autogen_complete_profile_allows_the_mimetypes_python311_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    from pysandboxes import guard_import
    from pysandboxes.e import RuleModuleNotFoundError

    path = _ROOT / "autogen-demo/.py-sandboxes-complete"
    lines = [
        ConfigLine(text, path, number)
        for number, text in enumerate(path.read_text().splitlines(), start=1)
        if text.strip().startswith("python-import=")
    ]
    rules, _ = guard_import.parse_rules(lines, [])
    monkeypatch.setattr(guard_import, "_rules", rules)
    monkeypatch.setattr(guard_import, "_activated", True)

    # Python 3.11 mimetypes imports this top-level module while httpx initializes.
    guard_import._judge_user_import("posixpath")
    with pytest.raises(RuleModuleNotFoundError):
        guard_import._judge_user_import("subprocess")


@pytest.mark.parametrize(("sample", "profile"), _PROFILES)
def test_the_sample_declares_its_sub_language(sample: str, profile: str) -> None:
    path = _ROOT / sample / profile
    assert path.exists(), f"{sample} has no {profile}"
    text = path.read_text()
    for line in _REQUIRED:
        assert line in text, f"{path} is missing {line!r}"


@pytest.mark.parametrize(("sample", "profile"), _PROFILES)
def test_the_declared_lines_parse_into_the_intended_rules(sample: str, profile: str) -> None:
    """Presence of the text is weak; what matters is what it parses into.

    Only the eval- lines are parsed here. A whole-file parse would need to
    resolve the `net=` rules, whose hostnames make this depend on DNS.
    """
    path = _ROOT / sample / profile
    assert path.exists(), f"{sample} has no {profile}"
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
