import logging
from pathlib import Path
from typing import Tuple, List, Optional

from .main_logger import format_ruleref, format_error_list, ErrorMsg
from .types import ConfigLines

logger = logging.getLogger(__name__)


def parse_rules(rules: ConfigLines,
                errors: List[ErrorMsg],
                ) -> Tuple[str, bool, Optional[Path], ConfigLines]:
    from .os_sandbox import providers_factory
    other_rules = []
    provider_rule: ConfigLines = []
    providers_set = []
    use_py_sandbox = True
    learning_path=None
    for rule in rules:
        if rule.rule.startswith("--os-sandbox="):
            provider_rule.append(rule)
            provider = rule.rule[len("--os-sandbox="):].strip()
            if provider not in providers_factory:
                errors.append(
                    (f"{format_ruleref(rule)}: "
                     f"Invalid os-sandbox '{provider}'.",
                     rule.path,
                     rule.ln
                     )
                )
            providers_set.append(provider)
        elif rule.rule.startswith("--py-sandbox="):
            value = rule.rule.split("=", 1)[1].strip().lower()
            if value in ("", "true"):
                use_py_sandbox = True
            elif value == "false":
                use_py_sandbox = False
            else:
                errors.append(
                    (f"{format_ruleref(rule)}: "
                     f"Invalid value '{value}' for --py-sandbox. Use true or false.",
                     rule.path, rule.ln)
                )
        elif rule.rule.startswith("--learning="):
            if learning_path:
                continue
            value = rule.rule.split("=", 1)[1].strip().lower()
            learning_path=Path(value)
            if not learning_path.parent.exists():
                learning_path=None
                errors.append(
                    (f"{format_ruleref(rule)}: "
                     f"Invalid value '{value}' for --learning. "
                     f"The parent path must exist.",
                     rule.path, rule.ln)
                )

        else:
            other_rules.append(rule)

    if len(providers_set) > 1:
        all_error_lines = [format_ruleref(rule) for rule in provider_rule]
        errors.append(
            (
                f"{format_error_list(all_error_lines)}: "
                f"Multiple --os-sandbox parameters.",
                Path(""),
                0
            )
        )
        return 'errors', use_py_sandbox, learning_path, other_rules
    if not providers_set:
        return "subprocess", use_py_sandbox, learning_path, other_rules
    return providers_set[0], use_py_sandbox, learning_path, other_rules
