import logging
from pathlib import Path
from typing import Tuple, List

from .main_logger import format_ruleref, format_error_list, ErrorMsg
from .types import ConfigLines

logger = logging.getLogger(__name__)


def parse_rules(rules: ConfigLines,
                errors: List[ErrorMsg],
                ) -> Tuple[str, ConfigLines]:
    from .os_sandboxes import providers
    other_rules = []
    provider_rule: ConfigLines = []
    provider = []
    for rule in rules:
        if rule.rule.startswith("--os-sandbox="):
            provider_rule.append(rule)
            provider = rule.rule[len("--os-sandbox="):].strip()
            if provider not in providers:
                errors.append(
                    (f"{format_ruleref(rule)}: "
                     f"Invalid os-sandbox '{provider}'.",
                     rule.path,
                     rule.ln
                     )
                )
        else:
            other_rules.append(rule)

    if len(provider) > 1:
        all_error_lines = [format_ruleref(rule) for rule in provider_rule]
        errors.append(
            (
                f"{format_error_list(all_error_lines)}: "
                f"Multiple --os-sandbox parameters.",
                Path(""),
                0
            )
        )
        return 'errors', other_rules

    return provider, other_rules
