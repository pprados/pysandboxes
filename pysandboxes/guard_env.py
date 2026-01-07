import re
from pathlib import Path
from typing import Dict, List, Tuple


def _read_and_substitute_lines(
        path: Path, env_vars: Dict[str, str]
) -> List[str]:
    """
    Reads a file, filters out empty lines and comments, and performs variable
    substitution on the remaining lines.

    The function supports two substitution formats:
    1. ${VAR_NAME}: Replaces the placeholder with the value of VAR_NAME from
       the env_vars dictionary. If the variable is not found, it's replaced
       with an empty string.
    2. ${VAR_NAME:=default_value}: Replaces the placeholder with the value of
       VAR_NAME if it exists in env_vars. Otherwise, it uses the provided
       default_value.

    Args:
        path: The Path object pointing to the file to be read.
        env_vars: A dictionary containing the environment-like variables
                  for substitution.

    Returns:
        A list of strings, where each string is a processed and substituted
        line from the file.
    """
    pattern = re.compile(r"\$\{([a-zA-Z0-9_]+)(?::=(.*?))?\}")

    def substitute(match: re.Match) -> str:
        var_name = match.group(1)
        default_value = match.group(2)
        return env_vars.get(var_name,
                            default_value if default_value is not None else "")

    processed_lines: List[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.lstrip().startswith("#"):
                substituted_line = pattern.sub(substitute, stripped)
                processed_lines.append(substituted_line)
    return processed_lines


def parse_guard_envs(
        rules: List[str], source_vars: Dict[str, str]
) -> Tuple[Dict[str, str], List[str]]:
    """
    Processes a list of rules to create a new dictionary of variables.

    Args:
        rules: A list of rule strings, e.g., ["key=value", "key2=${source_key}"].
        source_vars: The original dictionary of variables to draw from.

    Returns:
        A new dictionary with the applied rules.
    """
    new_vars: Dict[str, str] = {}
    ignore_rules: List[str] = []

    # This pattern finds ${VAR} or ${VAR:=default} substitutions.
    subst_pattern = re.compile(r"\$\{([a-zA-Z0-9_]+)(?::=(.*?))?\}")

    def substitute_value(value_pattern: str) -> str:
        """Resolves a single value pattern, e.g., ${VAR:=default}."""
        return subst_pattern.sub(
            lambda m: source_vars.get(m.group(1),
                                      m.group(2) if m.group(2) is not None else ""),
            value_pattern
        )

    for rule in rules:
        if rule.startswith("--set-env="):
            rule = rule[len("--set-env="):]

            if "=" not in rule:
                print(f"Warning: Skipping malformed rule: {rule}", file=sys.stderr)
                continue

            key_pattern, value_pattern = rule.split("=", 1)

            # Case: Wildcard rule like *_API_KEY=${*_API_KEY}
            if "*" in key_pattern:
                # Convert wildcard to regex pattern
                regex_key = re.compile(
                    re.escape(key_pattern).replace("\\*", ".*"))
                for source_key, source_value in source_vars.items():
                    if regex_key.match(source_key):
                        # The rule implies copying the matched key-value pairs
                        new_vars[source_key] = source_value
            # Case: Simple rule like key=value or key=${VAR}
            else:
                new_vars[key_pattern] = substitute_value(value_pattern)
        elif rule.startswith("--unset-env="):
            rule = rule[len("--unset-env="):]
            del new_vars[rule]
        else:
            ignore_rules.append(rule.strip())

    return new_vars,ignore_rules


def main() -> None:
    """
    Parses command-line arguments to set environment variables and determine
    the execution command.
    """
    args = sys.argv[1:]

    flags: List[str] = []
    set_env_rules: List[str] = []
    command_start_index = 0

    # 1. Collect all initial arguments that are flags or rules
    for i, arg in enumerate(args):
        if arg.startswith('--set-env='):
            # Extract the rule part, e.g., "key=value"
            set_env_rules.append(arg.split("=", 1)[1])
        elif arg.startswith('--'):
            flags.append(arg)
        else:
            # Stop at the first argument that is not a flag or rule
            command_start_index = i
            break
    else:
        # This else corresponds to the for loop. It runs if the loop completed
        # without a 'break', meaning all arguments were flags/rules.
        command_start_index = len(args)

    print(f"--- Argument Parsing ---")
    print(f"Detected flags: {flags}")
    print(f"Detected env rules: {set_env_rules}")

    # Process the environment rules
    # We use the current process's environment variables as the source
    source_variables = dict(os.environ)
    print("\n--- Applying Environment Rules ---")
    if set_env_rules:
        newly_set_vars = parse_guard_envs(set_env_rules, source_variables)
        print("Generated variables:")
        for key, val in newly_set_vars.items():
            print(f"  {key}: {val}")
        # In a real application, you might update os.environ here:
        # os.environ.update(newly_set_vars)
    else:
        print("No --set-env rules found.")

    # The rest of the arguments form the potential command
    command_args = args[command_start_index:]

    # Check for the optional '-' separator and remove it if present
    if command_args and command_args[0] == '-':
        print("\nSeparator '-' found.")
        command_args.pop(0)

    # Analyze the remaining arguments to determine the action
    if not command_args:
        print("\nAction: Start REPL (Read-Eval-Print Loop).")
    elif command_args[0] == '-m':
        if len(command_args) > 1:
            module_name = command_args[1]
            module_args = command_args[2:]
            print(f"\nAction: Execute a module.")
            print(f"  Module: {module_name}")
            print(f"  Arguments: {module_args}")
        else:
            print("\nError: -m flag requires a module name.", file=sys.stderr)
    else:
        script_name = command_args[0]
        script_args = command_args[1:]
        print(f"\nAction: Execute a script.")
        print(f"  Script: {script_name}")
        print(f"  Arguments: {script_args}")
    print("------------------------")


if __name__ == "__main__":
    # To test this script, run it from your terminal.
    # Make sure to set some source environment variables first.
    #
    # In bash/zsh:
    # export MY_USER=admin
    # export PROD_API_KEY=key-123-abc
    # export STAGING_API_KEY=key-456-def
    #
    # Example 1: Set simple value, use substitution with default, and run script
    # python your_script.py --set-env=DB_HOST=localhost --set-env=USER=${MY_USER} --set-env=PORT=${DB_PORT:=5432} my_app.py
    #
    # Example 2: Use wildcard to copy all API keys
    # python your_script.py --set-env=*_API_KEY=${*_API_KEY} -m my_module
    #
    main()
