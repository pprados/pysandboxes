# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Check permissions and action pinning in GitHub workflows."""

from pathlib import Path
import re

import yaml

GITHUB = Path(__file__).parents[2] / ".github"


def test_api_documentation_limits_deploy_permissions_to_deploy_job() -> None:
    workflow = yaml.safe_load((GITHUB / "workflows" / "api-docs.yml").read_text())
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["jobs"]["build"].get("permissions", workflow["permissions"]) == {"contents": "read"}
    assert workflow["jobs"]["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}


def test_external_workflow_actions_use_immutable_revisions() -> None:
    for path in (GITHUB / "workflows").glob("*.yml"):
        workflow = yaml.safe_load(path.read_text())
        for job in workflow["jobs"].values():
            uses = [job.get("uses", ""), *(step.get("uses", "") for step in job.get("steps", []))]
            for action in uses:
                if action and not action.startswith("./"):
                    assert re.fullmatch(r"[^@]+@[0-9a-f]{40}", action), (path, action)


def test_dependabot_updates_actions_on_develop() -> None:
    config = yaml.safe_load((GITHUB / "dependabot.yml").read_text())
    assert config["version"] == 2
    assert any(
        update["package-ecosystem"] == "github-actions"
        and update["directory"] == "/"
        and update["target-branch"] == "develop"
        and update["schedule"]["interval"] == "weekly"
        for update in config["updates"]
    )
