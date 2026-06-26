# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Learning mode must be able to bootstrap from an absent configuration.

The sandbox process arms its guards, then reaches user code through one of two
branches: ``python_in_sb`` for ``python-sb``, or ``run_server`` for the SSE
daemon. Both make deferred imports of their own after arming -- ``run_server``
starts with ``import importlib`` -- and those imports are charged to the user's
``python-import`` rules.

The import guard only records instead of denying while
``is_learning_mode() and is_in_sandbox()`` both hold, so both flags have to be
raised at the moment the guards are armed. Raised any later, the server branch
dies on its own imports and learning cannot produce a first configuration:
``RuleModuleNotFoundError: Module named 'importlib' is not allowed by a rule``.
"""

from pathlib import Path

from pysandboxes import sandboxes
from tests.integration_tests.sample import run_in_sandbox


def _bootstrap_profile(tmp_path: Path, learned: Path) -> Path:
    """A profile that whitelists nothing: everything has to come from learning."""
    profile = tmp_path / "bootstrap.profile"
    profile.write_text("py-sandbox=true\n" "os-sandbox=subprocess\n" f"learn={learned}\n")
    return profile


def test_learning_bootstraps_the_sse_server_branch(tmp_path: Path) -> None:
    learned = tmp_path / "learned.profile"
    profile = _bootstrap_profile(tmp_path, learned)

    with sandboxes(sandboxes_config=profile):
        assert run_in_sandbox() == 42

    assert learned.exists(), "learning mode wrote no configuration"
    assert "python-import=" in learned.read_text(), "learning recorded no import rule"
