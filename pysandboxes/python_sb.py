import atexit
import logging
import os
import sys
from pathlib import Path
from typing import Dict

from dotenv import load_dotenv

from pysandboxes.all_rules import AllRules
from pysandboxes.config import CONFIG_NAME
from pysandboxes.py_sandbox import read_and_parse_config, activate_sandboxes
from pysandboxes.remote.run_daemon import shutdown

# from pathlib import Path

# from pysandboxes.py_sandbox import read_and_parse_config, activate_sandboxes
# from pysandboxes.sb_types import ConfigLines

load_dotenv()  # FIXME: a garder avec main ?


def _python_interactive(all_rules: AllRules,
                        envs: Dict[str, str],
                        ):
    # activate_sandboxes(all_rules,
    #                    envs=dict(os.environ))
    # TODO: le envs final doit être injecté proprement
    sb_mode = f'APIs are LIMITED according to the rules in the {CONFIG_NAME!r} file.\n'
    if not Path(CONFIG_NAME).exists():
        sb_mode = (f'API calls are LEARNED and saved in {CONFIG_NAME!r} at the '
                   f'end of the program.\n')
    banner: str = (
        f'SANDBOXES Python {sys.version} on {sys.platform}\n'
        f'{sb_mode}'
        'Type "help", "copyright", "credits" or "license" for more information.'
    )
    prefix = "\u26A0 "

    try:
        # Try to import and use IPython for a better REPL experience
        import IPython
        raise ImportError()  # FIXME: force Python
        from traitlets.config import get_config
        c = get_config()

        # Update the prompt
        from IPython.terminal.prompts import Prompts, Token
        class CustomPrompts(Prompts):
            def in_prompt_tokens(self, cli=None):
                result = list(super().in_prompt_tokens())
                full_prompt = prefix + result[2][1]
                result[2] = result[2][0], full_prompt
                self.shell.prompt_length = len(full_prompt)
                return result

        c.TerminalIPythonApp.display_banner = False
        print(banner)
        print(
            f"IPython {IPython.__version__} -- An enhanced Interactive Python. Type '?' for help.")
        IPython.start_ipython(argv=[], user_ns=None,
                              config=c,
                              )
    except ImportError:
        # Fallback to the standard Python REPL if IPython is not installed
        import code

        # Create a banner for the standard REPL
        if hasattr(sys, 'ps1'):
            sys.ps1 = prefix + sys.ps1
        else:
            sys.ps1 = prefix + ">>> "

        # Start the standard interactive console
        code.interact(banner=banner, local={})


def _python_module(all_rules: AllRules,
                   envs: Dict[str, str],
                   module_name: str):
    import runpy
    import importlib
    module = importlib.import_module(module_name)
    activate_sandboxes(all_rules,
                       envs=dict(os.environ))
    runpy.run_module(module_name, run_name="__main__")


def _python_script(all_rules: AllRules,
                   envs: Dict[str, str],
                   script: str):
    activate_sandboxes(all_rules,
                       envs=dict(os.environ))
    exec(script)


def main() -> None:  # FIXME: véririfer CLI
    """
    Parses command-line arguments to separate flags from the execution command.
    """
    # Get all arguments except the script name itself
    args = sys.argv[1:]

    rules: Dict[str, str] = {}
    command_start_index = 0

    # 1. Collect all initial arguments that start with '--'
    for i, arg in enumerate(args):
        if arg.startswith('--'):
            if '=' in args:
                param, value = arg[2:].split("=", 1)
            else:
                param = arg[2:]
                value = ""
            rules[param] = value
            # Keep track of where the command part will start
            command_start_index = i + 1
        else:
            # Stop at the first argument that is not a flag
            break

    # The rest of the arguments form the potential command
    command_args = args[command_start_index:]
    # TODO: sous process si les parametres ne sont pas bon
    # TODO: execution dans notebook (__destructor__)
    # TODO: execution dans des TU en désactivatnt les annotations
    # TODO: gérer les paramètres multiples de mmeme nom lors de l'appel et du CLI (dans un tableau)
    # TODO: utiliser ia pour générer des github actions pour tester toutes versions
    # TODO: utilsier ia pour génerer doc de contribution
    # TODO: executer python-sb avec os-sandbox
    # TODO: intégrer REPL suivant les cas
    # TODO: tester installation au niveau user, pour tous les projets
    # TODO: améliorer la doc sur python-py
    # TODO: expliquer la stratégie d'implémentation (dans wiki?)
    # All standard single-character flags TODO
    # parser = argparse.ArgumentParser(
    #     description="Run a Python program in a sandbox.",
    #     epilog=textwrap.dedent("""
    #         usage: python [option] ... [-c cmd | -m mod | file | -] [arg] ...
    #         Options (and corresponding environment variables):
    #         """),
    #     add_help=False  # We'll add -h manually for full control
    # )
    # parser.add_argument("-h", "-?", "--help", action="store_true",
    #                     help="Print a short description of all command line options and corresponding environment variables and exit.")
    # parser.add_argument("--help-env", action="store_true",
    #                     help="Print a short description of Python-specific environment variables and exit.")
    # parser.add_argument("--help-xoptions", action="store_true",
    #                     help="Print a description of implementation-specific -X options and exit.")
    # parser.add_argument("--help-all", action="store_true",
    #                     help="Print complete usage information and exit.")
    # parser.add_argument("-V", "--version", action="store_true",
    #                     help="Print the Python version number and exit.")
    #
    # parser.add_argument("-b", action="store_true",
    #                     help="Issue a warning when converting bytes or bytearray to str without specifying encoding or comparing bytes or bytearray with str or bytes with int. Issue an error when the option is given twice (-bb).")
    # parser.add_argument("-B", action="store_true",
    #                     help="f given, Python won’t try to write .pyc files on the import of source modules. See also PYTHONDONTWRITEBYTECODE.")
    # parser.add_argument("--check-hash-based-pycs", action="store_true",
    #                     # default|always|never
    #                     help="Control the validation behavior of hash-based .pyc files.")
    # parser.add_argument("-d", action="store_true",
    #                     help="Turn on parser debugging output (for expert only)")
    # parser.add_argument("-E", action="store_true",
    #                     help="Ignore all PYTHON* environment variables, e.g. PYTHONPATH and PYTHONHOME, that might be set.")
    # parser.add_argument("-i", action="store_true",
    #                     help="Enter interactive mode after execution.")
    #
    # parser.add_argument("-I", action="store_true",
    #                     help="Run Python in isolated mode.")
    # parser.add_argument("-O", action="store_true",
    #                     help="Remove assert statements and any code conditional on the value of __debug__.")
    # parser.add_argument("-OO", action="store_true",
    #                     help="Do -O and also discard docstrings. ")
    # parser.add_argument("-P", action="store_true",
    #                     help="Don’t prepend a potentially unsafe path to sys.path")
    # parser.add_argument("-q", action="store_true",
    #                     help="Don’t display the copyright and version messages even in interactive mode.")
    # parser.add_argument("-R", action="store_true",
    #                     help="Turn on hash randomization.")
    # parser.add_argument("-s", action="store_true",
    #                     help="Don’t add the user site-packages directory to sys.path.")
    # parser.add_argument("-S", action="store_true",
    #                     help="Disable the import of the module site and the site-dependent manipulations of sys.path that it entails. ")
    # parser.add_argument("-u", action="store_true",
    #                     help="Force the stdout and stderr streams to be unbuffered. ")
    # parser.add_argument("-v", action="store_true",
    #                     help="Print a message each time a module is initialized, showing the place (filename or built-in module) from which it is loaded. ")
    # parser.add_argument("-W", action="append", metavar="ARG", dest="warnings",
    #                     help="Warning control. Python’s warning machinery by default prints warning messages to sys.stderr.")
    # parser.add_argument("-x", action="store_true",
    #                     help="Skip first line of source, allowing use of non-Unix forms of #!.")
    # parser.add_argument("-X", action="store", metavar="OPT", dest="xoptions",
    #                     help="Reserved for various implementation-specific options. ")
    #
    # parser.add_argument("-m", action="store", metavar="MOD", dest="module",
    #                     help="Run library module as a script (terminates option list).")
    # parser.add_argument("-c", action="store", metavar="CMD", dest="command",
    #                     help="Program passed in as a string.")

    # 2. Check for the optional '-' separator and remove it if present
    if command_args and command_args[0] == '-':
        command_args.pop(0)

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(levelname)-5s [%(process)d] %(name)s: %(message)s'
    )
    logging.getLogger("pysandboxes").setLevel(logging.WARNING)
    logging.getLogger("Pysandboxes").setLevel(
        logging.INFO)  # TODO: with parameter level ?
    all_rules = read_and_parse_config(
        config_path=None,
        **rules
    )

    atexit.register(shutdown)
    # 4. Analyze the remaining arguments to determine the action
    if not command_args or command_args[0] == '-i':
        _python_interactive(all_rules,
                            envs=dict(os.environ))
        # Case: No command arguments left, enter REPL mode
        # In a real application, you would start an interactive session:



    elif command_args[0] == '-m':
        # Case: Execute a module
        if len(command_args) > 1:
            module_name = command_args[1]
            command_args.pop(1)
            # command_args[0] = module.__file__
            sys.argv = command_args
            _python_module(all_rules, dict(os.environ), module_name)
        else:
            # Error case for '-m' without a module name
            print("\nError: -m flag requires a module name.", file=sys.stderr)

    elif command_args[0] == '-c':
        # Case: Execute a module
        if len(command_args) > 1:
            script = command_args[1]
            command_args.pop(1)
            sys.argv = command_args
            _python_script(all_rules, dict(os.environ), cript)
        else:
            # Error case for '-m' without a module name
            print("\nError: -c flag requires a script.", file=sys.stderr)

    else:
        # Case: Execute a script
        script_name = command_args[0]
        sys.argv = command_args
        script = Path(script_name).read_text()
        activate_sandboxes(all_rules,
                           envs=dict(os.environ))
        exec(script)


if __name__ == "__main__":
    main()
