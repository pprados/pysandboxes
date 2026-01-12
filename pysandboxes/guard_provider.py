import logging
from typing import Tuple, List
from .remote.os_sandbox import providers

logger = logging.getLogger(__name__)

def parse_rules(rules: List[str]) -> Tuple[str, List[str]]:
    other_rules = []
    provider=None
    for rule in rules:
        if rule.startswith("--os-sandbox="):
            provider = rule[len("--os-sandbox="):].strip()
            if provider not in providers:
                raise ValueError(f"Invalid os-sandbox: {provider}")
        else:
            other_rules.append(rule)
    return provider, other_rules
