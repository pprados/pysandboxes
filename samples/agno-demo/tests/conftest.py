"""Test configuration and fixtures for agno-demo sandbox tests."""

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_sandbox_config() -> None:
    """Configure PySandboxes to find .py-sandboxes config in project root.

    PySandboxes looks for configuration files in:
    1. Current working directory (.py-sandboxes)
    2. Package resources
    3. Environment variables

    This fixture ensures tests run with the correct sandbox configuration.
    """
    # Get the project root (samples/agno-demo/)
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)
