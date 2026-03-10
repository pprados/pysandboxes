# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, List, Tuple, cast

from .config import CONFIG_NAME
from .main_logger import ErrorMsg, format_error_list, format_ruleref
from .sb_types import ConfigLine, ConfigLines

logger = logging.getLogger(__name__)


def parse_rules(
    config_path: Path,
    rules: ConfigLines,
    errors: List[ErrorMsg],
) -> Tuple[int, str, bool, Path, bool, ConfigLines]:
    from .os_sandbox import providers_factory

    port = -1
    other_rules: ConfigLines = []
    parameters_multi_values: dict[str, set[Tuple[Any, ConfigLine]]] = defaultdict(set)
    use_py_sandbox = True
    learning_path = None

    for rule in rules:
        if rule.rule.startswith("os-sandbox="):
            provider = rule.rule[len("os-sandbox=") :].strip().lower()
            if provider not in providers_factory:
                errors.append(
                    (
                        f"{format_ruleref(rule)}: " f"Invalid os-sandbox {provider!r}.",
                        rule.path,
                        rule.ln,
                    )
                )
            else:
                parameters_multi_values["os-sandbox"].add((provider, rule))
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
            parameters_multi_values["py-sandbox"].add((use_py_sandbox, rule))
        elif rule.rule.startswith("port="):
            value = rule.rule.split("=", 1)[1].strip()
            try:
                port = int(value)
                if port < 0:
                    errors.append(
                        (
                            "Port must be a positive value",
                            rule.path,
                            rule.ln,
                        )
                    )
                    port = -1
                parameters_multi_values["port"].add((port, rule))
            except ValueError:
                errors.append(
                    (
                        "Port must be a positive value",
                        rule.path,
                        rule.ln,
                    )
                )

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
                parameters_multi_values["learning_path"].add((learning_path, rule))
                parameters_multi_values["learn"].add((True, rule))

        else:
            other_rules.append(rule)

    # Check multi-values. provider from command line is prioritized
    parameters_prioritize_single_value: dict[str, Any] = {}
    for k, s in parameters_multi_values.items():
        # Search the value from parameter
        for v, rule in s:
            if rule.path == Path("."):
                if len(s) <= 2:
                    parameters_prioritize_single_value[k] = (v, rule)
                    break
        else:
            if len(s) > 1:
                all_error_lines = [format_ruleref(rule) for _, rule in s]
                errors.append(
                    (
                        f"{format_error_list(all_error_lines)}: "
                        f"Multiple {k} parameters.",
                        Path(""),
                        0,
                    )
                )
            else:
                parameters_prioritize_single_value[k] = list(s)[0]

    provider = parameters_prioritize_single_value.get("os-sandbox", ["subprocess"])[0]
    use_py_sandbox = parameters_prioritize_single_value.get("py-sandbox", [True])[0]
    learning_path = parameters_prioritize_single_value.get(
        "learning_path", [config_path]
    )[0]
    learn: bool = cast(
        bool, parameters_prioritize_single_value.get("learn", [False])[0]
    )
    if learning_path is None:
        learning_path = config_path

    # Remove learn mode if py-sandbox=False
    if not use_py_sandbox:
        learn = False
    # Force learn mode if the file not exists
    elif not learning_path.exists():
        learn = True

    if errors:
        return port, "error", use_py_sandbox, learning_path, learn, other_rules
    return port, provider, use_py_sandbox, learning_path, learn, other_rules


# Tuple[int, str, bool, Path, bool, ConfigLines]:
