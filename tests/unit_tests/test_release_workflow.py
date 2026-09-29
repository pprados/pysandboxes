# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Structure of .github/workflows/release.yml: publication waits for every gate.

A guard against an honest mistake in the workflow, not against an attack: whoever can change release.yml can
change this test too. What stops a malicious change is outside the repository (tag ruleset, testpypi reviewer).
"""

from pathlib import Path
from typing import Any

import yaml

WORKFLOW = Path(__file__).parents[2] / ".github" / "workflows" / "release.yml"
GATES = {"verify", "build", "reuse-lookup", "full-gate", "wheel-tests"}


def _jobs() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]


def _needs(job: dict[str, Any]) -> set[str]:
    needs = job.get("needs", [])
    return {needs} if isinstance(needs, str) else set(needs)


def _publish() -> dict[str, Any]:
    return _jobs()["publish-testpypi"]


def _condition() -> str:
    return " ".join(_publish()["if"].split())


def test_publication_needs_every_gate() -> None:
    assert _needs(_publish()) >= GATES


def test_publication_runs_in_the_reviewed_testpypi_environment() -> None:
    assert _publish()["environment"]["name"] == "testpypi"


def test_publication_requires_the_build_and_the_wheel_tests() -> None:
    condition = _condition()
    assert "!cancelled()" in condition
    assert "needs.build.result == 'success'" in condition
    assert "needs.wheel-tests.result == 'success'" in condition
    assert "needs.reuse-lookup.result == 'success'" in condition


def test_a_skipped_full_gate_passes_only_through_the_reuse_lookup() -> None:
    assert "(needs.reuse-lookup.outputs.reuse == 'true' || needs.full-gate.result == 'success')" in _condition()


def test_the_full_gate_is_skipped_only_when_a_nightly_is_reused() -> None:
    full_gate = _jobs()["full-gate"]
    assert full_gate["uses"] == "./.github/workflows/full-gate.yml"
    assert full_gate["if"] == "needs.reuse-lookup.outputs.reuse != 'true'"
    assert full_gate["with"]["exclude-tcg"] is True


def test_the_wheel_tests_run_on_every_claimed_interpreter() -> None:
    wheel_tests = _jobs()["wheel-tests"]
    assert "build" in _needs(wheel_tests)
    assert "if" not in wheel_tests
    assert wheel_tests["strategy"]["matrix"]["python-version"] == [
        "3.11",
        "3.12",
        "3.13",
        "3.14",
    ]


def test_the_build_waits_for_the_light_gate() -> None:
    assert _needs(_jobs()["build"]) >= {"verify", "push-checks", "validate"}
