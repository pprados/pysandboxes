# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
import logging
from pathlib import Path
from typing import List, Tuple

from .config import CONFIG_NAME
from .main_logger import ErrorMsg, format_error_list, format_ruleref
from .sb_types import ConfigLines

logger = logging.getLogger(__name__)


def parse_rules(
        config_path: Path,
        rules: ConfigLines,
        errors: List[ErrorMsg],
) -> Tuple[int, str, bool, Path | None, bool, ConfigLines]:
    from .os_sandbox import providers_factory

    port=-1
    other_rules = []
    provider_rule: ConfigLines = []
    providers_set = []
    use_py_sandbox = True
    learning_path = None
    learn = False

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
            if value in ("", "true", "1"):
                use_py_sandbox = True
            elif value in ("false", "none", "0"):
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
        elif rule.rule.startswith("port="):
            value = rule.rule.split("=", 1)[1].strip()
            try:
                port = int(value)
                if port < 0:
                    errors.append(
                        ("Port must be a positive value",
                         rule.path,
                         rule.ln,
                         ))
                    port = -1
            except ValueError:
                errors.append(
                    ("Port must be a positive value",
                     rule.path,
                     rule.ln,
                     ))

        elif rule.rule.startswith("learn="):
            if learning_path:
                continue  # FIXME: error? prio for args?
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
                learn = True

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
        return port, "error", use_py_sandbox, learning_path, learn, other_rules
    elif len(providers_set) == 1:
        provider = providers_set[0][0]
    else:
        provider = "subprocess"  # default value

    if learning_path is None:
        learning_path = config_path

    # Remove learn mode if py-sandbox=False
    if not use_py_sandbox:
        learn = False
    # Force learn mode if the file not exists
    elif not learning_path.exists():
        learn = True

    return port, provider, use_py_sandbox, learning_path, learn, other_rules
