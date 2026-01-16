import logging
from typing import Tuple

from .types import ConfigLines

logger = logging.getLogger(__name__)

def parse_rules(rules: ConfigLines) -> Tuple[str, ConfigLines]:
    other_rules = []
    provider=None
    for rule in rules:
        if rule.startswith("--os-sandbox="):
            provider = rule[len("--os-sandbox="):].strip()
            # FIXME: desactivé pour prestarted
            # if provider not in providers:
            #     raise ValueError(f"Invalid os-sandbox: {provider}")
        else:
            other_rules.append(rule)
    return provider, other_rules
