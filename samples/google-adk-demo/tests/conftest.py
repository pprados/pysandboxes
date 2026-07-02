"""Pytest configuration and fixtures for google-adk-demo tests."""

from pathlib import Path

import pytest
from pysandboxes import sandboxes


@pytest.fixture
def sandbox_context():
    """Fixture that provides a sandbox context for tests.

    This fixture sets up the sandbox daemon for tests that need it.
    It configures the sandbox using the .py-sandboxes file in the project root.
    """
    config_path = Path(__file__).parent.parent / ".py-sandboxes"
    with sandboxes(sandboxes_config=config_path):
        yield
