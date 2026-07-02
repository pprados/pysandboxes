"""Pytest configuration for openai-agents-sdk-demo tests.

Sets the import path and the working directory the profiles are resolved from.

It deliberately does NOT weaken the sandbox. It used to set
``OS_SANDBOX=none``, which every subprocess inherited -- and with the OS
provider off, `py-sandbox=true` guards nothing: the escape succeeds and a host
outside `net=ALLOW` is fetched. A test suite that disables what it is meant to
verify cannot fail.
"""

import os
import sys
from pathlib import Path

# Add the project root to sys.path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# The profiles are resolved from the sample root
os.chdir(project_root)
