"""Pytest configuration for the MCP server demo tests.

Puts the sample root on ``sys.path`` so ``mcp_server`` is importable. Nothing
here disarms the sandbox: the scenarios differ only by the arguments they hand
to ``sandboxes()``, which is precisely what they compare.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
