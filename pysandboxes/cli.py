import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv

from pysandboxes.py_sandbox import activate_sandboxes
from pysandboxes.types import ConfigLines

load_dotenv()  # FIXME: a garder avec main ?

def main() -> None:
    """
    Parses command-line arguments to separate flags from the execution command.
    """
    # Get all arguments except the script name itself
    args = sys.argv[1:]

    rules: ConfigLines = []
    command_start_index = 0

    # 1. Collect all initial arguments that start with '--'
    for i, arg in enumerate(args):
        if arg.startswith('--'):
            rules.append(arg)
            # Keep track of where the command part will start
            command_start_index = i + 1
        else:
            # Stop at the first argument that is not a flag
            break

    # The rest of the arguments form the potential command
    command_args = args[command_start_index:]

    # 2. Check for the optional '-' separator and remove it if present
    if command_args and command_args[0] == '-':
        command_args.pop(0)

    # 4. Analyze the remaining arguments to determine the action
    if not command_args:
        # Case: No command arguments left, enter REPL mode
        # In a real application, you would start an interactive session:
        activate_sandboxes(args_rules=rules)

        import code
        code.interact()

    elif command_args[0] == '-m':
        # Case: Execute a module
        if len(command_args) > 1:
            module_name = command_args[1]
            import runpy
            import importlib
            module = importlib.import_module(module_name)
            command_args.pop(1)
            command_args[0] = module.__file__
            sys.argv = command_args
            activate_sandboxes(args_rules=rules)
            runpy.run_module(module_name, run_name="__main__")
        else:
            # Error case for '-m' without a module name
            print("\nError: -m flag requires a module name.", file=sys.stderr)

    elif command_args[0] == '-c':
        # Case: Execute a module
        if len(command_args) > 1:
            script = command_args[1]
            command_args.pop(1)
            sys.argv = command_args
            activate_sandboxes(args_rules=rules)
            exec(script)
        else:
            # Error case for '-m' without a module name
            print("\nError: -c flag requires a script.", file=sys.stderr)

    else:
        # Case: Execute a script
        script_name = command_args[0]
        sys.argv = command_args
        script = Path(script_name).read_text()
        activate_sandboxes(args_rules=rules)  # FIXIE: ou via le lancement du process ? ou exec ?
        exec(script)


if __name__ == "__main__":
    main()
