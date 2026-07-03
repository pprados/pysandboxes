# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Pytest configuration for smolagents-demo tests.

Sets the working directory the profiles are resolved from.

It used to re-export `samples/conftest.py`, whose fixtures generated a profile
containing `python-import=*` -- a wildcard that voids the whitelist these tests
exist to demonstrate. That shared harness is gone.
"""

import os
from pathlib import Path

os.chdir(Path(__file__).parent.parent)
