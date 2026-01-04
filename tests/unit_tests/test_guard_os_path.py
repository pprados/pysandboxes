import os
import pytest
from io import open_code

from langgraph_codeagent.sandboxes.guard_files import activate_guard_files
@pytest.fixture(autouse=True)
def reset_rules():
    from langgraph_codeagent.sandboxes.guard_files import deactivate_guard_files

    yield
    print("desactivate")  # FIXME
    deactivate_guard_files()





