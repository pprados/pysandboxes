# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Pytest configuration for langgraph-demo tests.

This module sets up the test environment: the import path, and the working
directory the profiles are resolved from.

It deliberately does NOT weaken the sandbox. It used to set
``OS_SANDBOX=none``, which every subprocess inherited -- including the
complete-mode run under `python-sb`, where the escape then succeeded and the
denied host was fetched. A test suite that disables what it is meant to verify
cannot fail.
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
