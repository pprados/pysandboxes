import logging
from typing import Tuple, List
from .remote.providers import providers

logger = logging.getLogger(__name__)

def parse_rules(rules: List[str]) -> Tuple[str, List[str]]:
    other_rules = []
    provider=None
    for rule in rules:
        if rule.startswith("--sandbox-provider="):
            provider = rule[len("--sandbox-provider="):].strip()
            if provider not in providers:
                raise ValueError(f"Invalid sandbox-provider: {provider}")
        else:
            other_rules.append(rule)
    return provider, other_rules
