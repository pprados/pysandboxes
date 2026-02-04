import logging
import sys
from types import ModuleType
from typing import Dict, Any, Set


def save_default_values(
        memory: Dict[str, Any],
        keys: Set[str],
        module: ModuleType):
    for name in keys:
        val = module
        for m in name.split('.'):
            if hasattr(val, m):
                val = getattr(val, m)
            else:
                val = None
                logging.warning("save default value: Could not find %s",name)
                break
        if val:
            memory[name] = val


