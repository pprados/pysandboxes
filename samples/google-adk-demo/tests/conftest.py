# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Pytest configuration for google-adk-demo tests.

Sets the working directory the profiles are resolved from. The tests arm the
sandbox themselves, per test, so that each one states which profile it runs
under instead of inheriting it from a fixture.
"""

import os
from pathlib import Path

os.chdir(Path(__file__).parent.parent)
