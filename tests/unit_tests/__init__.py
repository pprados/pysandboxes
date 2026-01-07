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
                logging.warning("Could not find %s",name)
                break
        if val:
            memory[name] = val


def restore_default_values(memory: Dict[str, Any], module: ModuleType):
    for name, v in memory.items():
        obj = module
        part_names = name.split('.')
        for m in part_names[:-1]:
            obj = getattr(obj, m)
        setattr(obj, part_names[-1], v)
