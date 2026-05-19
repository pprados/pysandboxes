"""Shared test configuration for samples.

Provides fixtures for pysandbox testing across all samples.
"""

import contextlib
import os
from pathlib import Path
from typing import Generator

import pytest


# URLs for testing
ALLOWED_URL = "https://example.com"
BLOCKED_URL = "https://blocked-domain.example.local"


@contextlib.contextmanager
def pysandbox_enabled() -> Generator[None, None, None]:
    """Context manager: activate pysandboxes for test scope."""
    old_py = os.environ.get("PYSANDBOX_PY")
    old_os = os.environ.get("PYSANDBOX_OS")

    try:
        os.environ["PYSANDBOX_PY"] = "true"
        os.environ["PYSANDBOX_OS"] = os.environ.get("PYSANDBOX_OS", "subprocess")
        yield
    finally:
        if old_py is None:
            os.environ.pop("PYSANDBOX_PY", None)
        else:
            os.environ["PYSANDBOX_PY"] = old_py
        if old_os is None:
            os.environ.pop("PYSANDBOX_OS", None)
        else:
            os.environ["PYSANDBOX_OS"] = old_os


def create_sandbox_config(allowed_urls: list[str] | None = None) -> str:
    """Generate .py-sandboxes config for testing.

    Args:
        allowed_urls: URLs to allow outbound access to.

    Returns:
        Config content.
    """
    config_lines = [
        "py-sandbox=true",
        "os-sandbox=subprocess",
        "env=HOME=${HOME}",
        "",
        "# Standard & external imports",
        "python-import=*",
        "",
        "# Network: allow specific hosts, default deny",
    ]

    if allowed_urls:
        for url in allowed_urls:
            host = url.replace("https://", "").replace("http://", "").split("/")[0]
            config_lines.extend([
                f"net=ALLOW|TCP|{host}|443|OUT",
                f"net=ALLOW|TCP|{host}|80|OUT",
            ])

    config_lines.extend(["", "expose-ro=."])
    return "\n".join(config_lines)


@pytest.fixture
def sandbox_config_allow_example(tmp_path: Path) -> Path:
    """Fixture: config allowing example.com."""
    config_file = tmp_path / ".py-sandboxes"
    config_file.write_text(create_sandbox_config(allowed_urls=[ALLOWED_URL]))
    return config_file


@pytest.fixture
def sandbox_config_deny_all(tmp_path: Path) -> Path:
    """Fixture: config denying all external access."""
    config_file = tmp_path / ".py-sandboxes"
    config_file.write_text(create_sandbox_config(allowed_urls=[]))
    return config_file
