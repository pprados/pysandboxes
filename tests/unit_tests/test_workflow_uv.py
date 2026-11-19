# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Check uv installation in the CI and release workflows."""

from pathlib import Path
import re

import pytest
import yaml

WORKFLOWS = Path(__file__).parents[2] / ".github" / "workflows"
ACTION = "astral-sh/setup-uv@68559e99cc807c1eb7e9238fd43a15bba460eec2"


@pytest.mark.parametrize(
    ("filename", "expected_installations"),
    [
        ("lint.yml", 1),
        ("test.yml", 2),
        ("integration.yml", 1),
        ("containers.yml", 1),
        ("samples.yml", 2),
        ("api-docs.yml", 1),
        ("release.yml", 3),
        ("images.yml", 1),
        ("cross-os.yml", 1),
        ("crewai-macos.yml", 1),
    ],
)
def test_uv_installations_are_pinned_and_verified(filename: str, expected_installations: int) -> None:
    workflow = yaml.safe_load((WORKFLOWS / filename).read_text())
    installations = 0
    for job in workflow["jobs"].values():
        steps = job.get("steps", [])
        for index, step in enumerate(steps):
            if step.get("name") != "Install uv":
                continue
            installations += 1
            assert step.get("uses") == ACTION
            assert step.get("with", {}).get("version") == "0.11.16"
            assert steps[index + 1].get("run") == 'test "$(uv --version)" = "uv 0.11.16"'
    assert installations == expected_installations


def test_all_workflows_avoid_unpinned_uv_installers() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                action = step.get("uses", "")
                if action.startswith("astral-sh/setup-uv@"):
                    assert action == ACTION, path
                    assert step.get("with", {}).get("version") == "0.11.16", path
                run = step.get("run", "")
                assert not re.search(r"(?:astral\.sh/uv/|\bpip\s+install\s+uv\b)", run), path
