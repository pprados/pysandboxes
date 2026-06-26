"""Pytest configuration for MCP server tests.

Configures path for importing mcp_server package.
"""

import sys
from pathlib import Path

# Add parent directory to path so mcp_server can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))
