"""Pytest configuration for autogen-demo tests.

Configures path for importing autogen_demo package and sets up sandbox environment.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path so autogen_demo can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure sandbox to use subprocess provider (safe for testing)
# This ensures @sandbox decorator runs functions in isolated subprocess
os.environ.setdefault("OS_SANDBOX", "subprocess")
