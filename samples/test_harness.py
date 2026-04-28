"""Shared test harness for sandbox verification across samples.

Tests two scenarios:
1. Global sandbox mode: pysandboxes enforces network rules
2. @pysandbox decorator: annotation-based sandbox enforcement
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
def pysandbox_enabled(config_path: Path | None = None) -> Generator[None, None, None]:
    """Context manager: activate pysandboxes for test scope.

    Sets environment to run code through pysandboxes sandbox.
    """
    old_sandbox_py = os.environ.get("PYSANDBOX_PY")
    old_sandbox_os = os.environ.get("PYSANDBOX_OS")

    try:
        os.environ["PYSANDBOX_PY"] = "true"
        os.environ["PYSANDBOX_OS"] = os.environ.get("PYSANDBOX_OS", "subprocess")
        yield
    finally:
        if old_sandbox_py is None:
            os.environ.pop("PYSANDBOX_PY", None)
        else:
            os.environ["PYSANDBOX_PY"] = old_sandbox_py
        if old_sandbox_os is None:
            os.environ.pop("PYSANDBOX_OS", None)
        else:
            os.environ["PYSANDBOX_OS"] = old_sandbox_os


def create_sandbox_config(
    allowed_urls: list[str] | None = None,
    blocked_urls: list[str] | None = None,
) -> str:
    """Generate .py-sandboxes config content for testing.

    Args:
        allowed_urls: List of URLs to allow (TCP:80/443 OUT)
        blocked_urls: Ignored (default deny-all is sufficient)

    Returns:
        Config content as string
    """
    config_lines = [
        "py-sandbox=true",
        "os-sandbox=subprocess",
        "env=HOME=${HOME}",
        "",
        "# Standard imports",
        "python-import=*",
        "",
        "# Network: allow specific hosts, default deny",
    ]

    if allowed_urls:
        for url in allowed_urls:
            # Extract hostname from URL
            host = url.replace("https://", "").replace("http://", "").split("/")[0]
            config_lines.append(f"net=ALLOW|TCP|{host}|443|OUT")
            config_lines.append(f"net=ALLOW|TCP|{host}|80|OUT")

    config_lines.append("")
    config_lines.append("ro-bind=.,.")

    return "\n".join(config_lines)


@pytest.fixture
def sandbox_config_path(tmp_path: Path) -> Path:
    """Fixture: provide .py-sandboxes config path in temp directory."""
    config_file = tmp_path / ".py-sandboxes"
    config_file.write_text(create_sandbox_config(allowed_urls=[ALLOWED_URL]))
    return config_file
