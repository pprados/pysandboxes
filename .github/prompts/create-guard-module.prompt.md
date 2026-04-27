---
description: 'Scaffold a new security guard module following the project''s guard_*.py pattern with parse_rules(), patch_rules(), NamedTuple rule classes, and learning mode support.'
agent: 'agent'
---

Scaffold a new security guard module following the project's guard_*.py pattern with parse_rules(), patch_rules(), NamedTuple rule classes, and learning mode support.

## When to Use

- Adding a new security enforcement dimension to the sandbox (e.g., guard_subprocess.py, guard_signals.py)
- Extending the sandbox security model with a new category of restrictions

## Context Validation Checkpoints

* [ ] What security domain does this guard enforce (e.g., subprocess, signals, memory)?
* [ ] What Python stdlib functions or modules need to be monkey-patched?
* [ ] What configuration syntax will users use to define rules?

## Command Steps

### Step 1: Create the guard file

Create pysandboxes/guard_<domain>.py with the standard structure: imports, NamedTuple rule classes, parse_rules(), and patch_rules().

from typing import Callable, NamedTuple
from pysandboxes._typing import ConfigLines, ErrorMsg

class DomainRule(NamedTuple):
    pattern: str
    action: str

class LearnDomainRule(NamedTuple):
    pattern: str
    observed_at: str

def parse_rules(config_lines: ConfigLines, errors: list[ErrorMsg]) -> tuple[tuple[DomainRule, ...], tuple[LearnDomainRule, ...]]:
    rules: list[DomainRule] = []
    for line in config_lines:
        rules.append(DomainRule(pattern=line.strip(), action="allow"))
    return tuple(rules), ()

def patch_rules(learn: bool) -> dict[str, Callable]:
    if learn:
        return {"target.func": _learn_wrapper}
    return {"target.func": _enforce_wrapper}

### Step 2: Register in all_rules.py

Add the new guard's rules to the AllRules NamedTuple and wire parse_rules() into load_and_parse_config().

### Step 3: Add configuration section

Define the configuration syntax in a .profile file section (e.g., [domain]) and document accepted rule formats.

### Step 4: Write tests

Create tests/unit_tests/guard/test_guard_<domain>.py with tests for parse_rules() and patch_rules() in both learn and enforce modes.
