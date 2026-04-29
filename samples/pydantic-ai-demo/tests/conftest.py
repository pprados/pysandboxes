"""Test configuration and fixtures for pydantic-ai-demo.

This module configures pytest and provides shared fixtures for all tests.
It ensures the sandbox configuration is properly loaded when running tests.
"""

from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def configure_pysandboxes_path() -> None:
    """Configure pysandboxes to find .py-sandboxes config in sample directory.

    This ensures that when tests use @sandbox decorator, the configuration
    is loaded from the correct location.
    """
    from pysandboxes import sandboxes
    # The .py-sandboxes file should be in the sample directory
    # PySandboxes will automatically search for it in the current directory
    # and parent directories, so this fixture documents the expectation
    config_path = Path(__file__).parent.parent / ".py-sandboxes"
    assert config_path.exists(), f"Config file {config_path} should exist"
