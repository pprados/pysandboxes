"""Pytest configuration for openai-agents-sdk-demo tests.

This module sets up the test environment, including:
- Proper Python path configuration for imports
- Sandbox configuration file discovery
- Shared sandbox test fixtures
"""

import sys
import os
from pathlib import Path

# Add the project root to sys.path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Ensure sandbox config is discoverable from project root
# The .py-sandboxes file should be located in the project root
os.chdir(project_root)

# Disable OS-level sandboxing for unit tests
# Tests use Python-level guards and mocking instead
os.environ["OS_SANDBOX"] = "none"

# Import shared fixtures from samples/conftest.py
sys.path.insert(0, str(project_root.parent))

# Re-export fixtures from samples.conftest for local tests
pytest_plugins = ["conftest"]
