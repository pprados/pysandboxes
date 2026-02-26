import logging
from pathlib import Path
from typing import List, Tuple

from .config import CONFIG_NAME
from .main_logger import ErrorMsg, format_error_list, format_ruleref
from .sb_types import ConfigLines

logger = logging.getLogger(__name__)


def parse_rules(
        config_path:Path,
        rules: ConfigLines,
        errors: List[ErrorMsg],
) -> Tuple[str, bool, Path|None, bool, ConfigLines]:
    from .os_sandbox import providers_factory

    other_rules = []
    provider_rule: ConfigLines = []
    providers_set = []
    use_py_sandbox = True
    learning_path = None
    learning = False

    for rule in rules:
        if rule.rule.startswith("os-sandbox="):
            provider_rule.append(rule)
            provider = rule.rule[len("os-sandbox="):].strip().lower()
            if provider not in providers_factory:
                errors.append(
                    (
                        f"{format_ruleref(rule)}: " f"Invalid os-sandbox {provider!r}.",
                        rule.path,
                        rule.ln,
                    )
                )
            else:
                providers_set.append((provider, rule))
        elif rule.rule.startswith("py-sandbox="):
            value = rule.rule.split("=", 1)[1].strip().lower()
            if value in ("", "true"):
                use_py_sandbox = True
            elif value == "false":
                use_py_sandbox = False
            else:
                errors.append(
                    (
                        f"{format_ruleref(rule)}: "
                        f"Invalid value {value!r} for py-sandbox. Use true or false.",
                        rule.path,
                        rule.ln,
                    )
                )
        elif rule.rule.startswith("learn="):
            if learning_path:  # FIXME: error? prio for args?
                continue
            value = rule.rule.split("=", 1)[1].strip()
            if value.lower() in ("true", "false", "0", "1"):
                errors.append(
                    (
                        f"{format_ruleref(rule)}: "
                        f"Invalid value {value!r} for 'learn'. "
                        f"Use the filename instead.",
                        rule.path,
                        rule.ln,
                    )
                )
            else:
                if value:
                    learning_path = Path(value)
                    if learning_path.parent == Path("."):
                        # Use relative to the file with this parameter
                        learning_path = rule.path.parent / learning_path

                else:
                    learning_path = Path(CONFIG_NAME)
                if not learning_path.parent.exists():
                    errors.append(
                        (
                            f"{format_ruleref(rule)}: "
                            f"Invalid value {value!r} for 'learn'. "
                            f"The parent path must exist.",
                            rule.path,
                            rule.ln,
                        )
                    )
                else:
                    learning = True

        else:
            other_rules.append(rule)

    # provider from command line is prioritized
    cmd_line_provider = list(filter(lambda x: x[1].ln == 0, providers_set))
    if len(cmd_line_provider) == 1:
        provider = cmd_line_provider[0][0]
    elif len(providers_set) > 1:
        all_error_lines = [format_ruleref(rule) for _, rule in providers_set]
        errors.append(
            (
                f"{format_error_list(all_error_lines)}: "
                f"Multiple os-sandbox parameters.",
                Path(""),
                0,
            )
        )
        return "errors", use_py_sandbox, learning_path, learning, other_rules
    elif len(providers_set) == 1:
        provider = providers_set[0][0]
    else:
        provider = "subprocess"  # default value

    if learning_path is None:
        learning_path = config_path

    # Force learn mode if the file not exists
    if not learning_path.exists() and not learning:
        learning = True

    return provider, use_py_sandbox, learning_path, learning, other_rules
