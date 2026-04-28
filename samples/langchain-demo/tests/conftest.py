"""Pytest configuration for langchain-demo tests.

This module sets up the test environment and provides fixtures for testing
both sandboxed and non-sandboxed implementations.
"""

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def configure_sandbox_environment() -> None:
    """Configure the sandbox environment for tests.

    Sets the working directory to the sample root so that .py-sandboxes
    configuration is discovered by the sandbox system.
    """
    # Ensure working directory is set to the sample directory
    sample_dir = Path(__file__).parent.parent
    os.chdir(sample_dir)


@pytest.fixture
def sample_url() -> str:
    """Provide a sample URL for testing."""
    return "https://example.com"


@pytest.fixture
def unauthorized_url() -> str:
    """Provide an unauthorized URL for testing sandbox restrictions."""
    return "https://malicious-domain.com"


@pytest.fixture
def large_html_content() -> str:
    """Provide large HTML content that will be truncated."""
    return "x" * 9000


@pytest.fixture
def small_html_content() -> str:
    """Provide small HTML content that won't be truncated."""
    return "<html><body>Small content</body></html>"
