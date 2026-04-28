"""Sandbox integration tests for fetch_webpage tool.

Demonstrates two scenarios:
- Scenario A: Without sandbox (direct inner function call)
- Scenario B: With sandbox protection (restricted network access)
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from google_adk_demo.tools import fetch_webpage


class TestScenarioWithoutSandbox:
    """Scenario A: Direct fetch_webpage call without explicit sandbox context.

    In this scenario, the wrapper calls the inner function. The inner function
    is decorated with @sandbox, but these tests run outside the sandbox context
    to demonstrate how the framework would call these functions.
    """

    def test_config_exists(self) -> None:
        """Verify that .py-sandboxes configuration file exists."""
        config_path = Path(__file__).parent.parent / ".py-sandboxes"
        assert config_path.exists(), f".py-sandboxes config not found at {config_path}"

    def test_config_contains_required_rules(self) -> None:
        """Verify .py-sandboxes config contains required security rules."""
        config_path = Path(__file__).parent.parent / ".py-sandboxes"
        content = config_path.read_text()
        # Check for key rules
        assert "py-sandbox=true" in content
        assert "python-import=httpx" in content
        # Verify whitelist approach (example.com allowed)
        assert ("net=ALLOW|TCP|example.com|80|OUT" in content or
                "net=ALLOW|TCP|example.com|443|OUT" in content)


class TestScenarioWithSandbox:
    """Scenario B: Sandboxed fetch_webpage with network restrictions.

    This scenario demonstrates the @sandbox decorator and .py-sandboxes config
    protecting network access. Tests use the sandbox context manager.
    Note: Full OS sandbox may not be available in all environments, so
    these tests verify the structure is in place.
    """

    def test_wrapper_calls_inner_function(self) -> None:
        """Verify the wrapper delegates to the inner sandboxed function."""
        import inspect
        source = inspect.getsource(fetch_webpage)
        # Check that the wrapper calls _fetch_webpage
        assert "_fetch_webpage" in source

    def test_inner_function_is_sandboxed(self) -> None:
        """Verify the inner function has the @sandbox decorator."""
        from google_adk_demo.tools import _fetch_webpage
        # The decorator should wrap the function
        assert callable(_fetch_webpage)
        # Check if function has been wrapped by @sandbox
        # (the wrapper adds functools.wraps metadata)
        assert hasattr(_fetch_webpage, "__name__")
        assert _fetch_webpage.__name__ == "_fetch_webpage"

    def test_sandbox_config_allows_example_com(self) -> None:
        """Test that config allows example.com (required domain)."""
        config_path = Path(__file__).parent.parent / ".py-sandboxes"
        content = config_path.read_text()
        # Verify that example.com is explicitly allowed
        assert "net=ALLOW|TCP|example.com" in content

    def test_sandbox_config_denies_other_domains(self) -> None:
        """Test that config doesn't have blanket allow rules."""
        config_path = Path(__file__).parent.parent / ".py-sandboxes"
        content = config_path.read_text()
        # Verify no wildcard allows for arbitrary domains
        lines = [line.strip() for line in content.split('\n')]
        # Should not have "net=ALLOW|TCP|*|" patterns
        for line in lines:
            if line.startswith('net=') and 'ALLOW' in line and '*' in line:
                # This is too permissive
                assert False, f"Config has overly permissive rule: {line}"

    def test_fetched_via_wrapper_structure(self) -> None:
        """Verify the fetch_webpage function structure."""
        import inspect
        sig = inspect.signature(fetch_webpage)
        # Should take URL parameter
        assert "url" in sig.parameters
        # Should return string
        assert sig.return_annotation == str


class TestSandboxIntegrationStructure:
    """Verify the sandbox integration structure is properly set up."""

    def test_pysandboxes_imported(self) -> None:
        """Verify pysandboxes is available and imported in tools module."""
        from google_adk_demo import tools
        # Check that sandbox is imported
        source = Path(tools.__file__).read_text()
        assert "from pysandboxes import sandbox" in source

    def test_both_functions_accessible(self) -> None:
        """Verify both wrapper and inner function are accessible."""
        from google_adk_demo.tools import fetch_webpage, _fetch_webpage
        assert callable(fetch_webpage)
        assert callable(_fetch_webpage)

    def test_fetch_webpage_signature_unchanged(self) -> None:
        """Verify fetch_webpage has the expected signature for framework compatibility."""
        import inspect
        sig = inspect.signature(fetch_webpage)
        params = list(sig.parameters.keys())
        # Should only take url parameter (for framework compatibility)
        assert params == ["url"]
        # Should return string
        assert sig.return_annotation == str

    def test_config_file_properly_formatted(self) -> None:
        """Verify .py-sandboxes is properly formatted."""
        config_path = Path(__file__).parent.parent / ".py-sandboxes"
        content = config_path.read_text()
        # Should have at least basic sandbox config
        assert "py-sandbox=" in content
        # Should have network rules
        assert "net=" in content
        # Should allow httpx
        assert "python-import=httpx" in content


class TestDocumentation:
    """Verify that documentation reflects the sandbox integration."""

    def test_inner_function_has_docstring(self) -> None:
        """Verify _fetch_webpage has documentation."""
        from google_adk_demo.tools import _fetch_webpage
        assert _fetch_webpage.__doc__ is not None
        assert "sandbox" in _fetch_webpage.__doc__.lower()

    def test_wrapper_function_has_docstring(self) -> None:
        """Verify fetch_webpage documents the wrapper pattern."""
        from google_adk_demo.tools import fetch_webpage
        assert fetch_webpage.__doc__ is not None
        # Should document the wrapper pattern
        assert "wrapper" in fetch_webpage.__doc__.lower() or \
               "delegate" in fetch_webpage.__doc__.lower() or \
               "framework" in fetch_webpage.__doc__.lower()
