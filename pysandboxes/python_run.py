import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, Dict, Union

from .config import CONFIG_NAME
from .remote.run_daemon import shutdown
from .sandboxes_api import sandbox, sandboxes

def _debug_log():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(levelname)-5s [%(process)d] %(name)s: %(message)s'
    )
    logging.getLogger("pysandboxes").setLevel(logging.WARNING)
    logging.getLogger("Pysandboxes").setLevel(
        logging.INFO)  # TODO: with parameter level ?


def _python_interactive(
        learning_path: Optional[Path],
):
    # TODO: le envs final doit être injecté proprement
    sb_mode = (f'APIs are LIMITED according to the rules in '
               f'the {str(learning_path)!r} file.\n')
    exit_msg = ""
    if learning_path:
        sb_mode = (f'API calls are LEARNED and saved in '
                   f'{str(learning_path)!r} at the '
                   f'end of the program.\n')
        exit_msg = f"Save the {CONFIG_NAME!r}"
    banner: str = (
        f'SANDBOXES Python {sys.version} on {sys.platform}\n'
        f'{sb_mode}'
        'Type "help", "copyright", "credits" or "license" for more information.'
    )
    prefix = "\u26A0 "

    try:
        # Try to import and use IPython for a better REPL experience
        import IPython
        # raise ImportError()  # FIXME: force Python
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

        c.TerminalInteractiveShell.prompts_class = CustomPrompts

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
        code.interact(banner=banner,
                      exitmsg=exit_msg,
                      # When self.local_exit is True, we overwrite the builtins so
                      # exit() and quit() only raises SystemExit and we can catch that
                      # to only exit the interactive shell
                      local_exit=True,
                      )

def _python_module(module_name: str):
    import runpy
    import importlib
    module = importlib.import_module(module_name)
    runpy.run_module(module_name, run_name="__main__")



def _python_script(script: str):
    exec(script)


def _sandbox_run_exec(
        python_cmd: List[str],  # -c, -m, -i ...
        learning_path: Optional[Path]

):
    pass


def _convert_extra_rules(args: List[str]) -> Dict[str, Union[str, List[str]]]:
    result = {}
    for rule in args:
        assert rule.startswith("--")
        if '=' in rule:
            key, val = rule.split('=', maxsplit=1)
        else:
            key, val = rule, ""  # Empty by default
        if key in result:
            result[key[2:]].append(val)
        else:
            result[key[2:]] = [val]
    return result



def _sandbox_run(
    python_parsed_args:List[str],
    sandboxes_args:List[str],
    python_cmd:List[str],
):
    """ Stratégie utilisant @sandbox. Ne gère pas correctement stdin """
    _debug_log()
    with sandboxes(
            envs=dict(os.environ),
            python_args=python_parsed_args,
            **_convert_extra_rules(sandboxes_args),
    ) as sb:

        __sandbox_run(
            python_cmd,
            sb.learning_path,
        )

@sandbox
def __sandbox_run(
        python_cmd: List[str],  # -c, -m, -i ...
        learning_path: Optional[Path]
):
    try:
        if not len(python_cmd) or python_cmd[0] == "-i" or python_cmd[0] == "-":
            _python_interactive(learning_path)
        elif python_cmd[0] == '-m':
            # Case: Execute a module
            if len(python_cmd) > 1:
                module_name = python_cmd[1]
                python_cmd.pop(
                    1)  # FIXME: vérifier la justification par rapport au classique
                # command_args[0] = module.__file__   # FIXME: vérifier la justification par rapport au classique
                sys.argv = python_cmd
                _python_module(module_name)
            else:
                # Error case for '-m' without a module name
                print("\nError: -m flag requires a module name.", file=sys.stderr)

        elif python_cmd[0] == '-c':
            # Case: Execute a module
            if len(python_cmd) > 1:
                script = python_cmd[1]
                python_cmd.pop(
                    1)  # FIXME: vérifier la justification par rapport au classique
                sys.argv = python_cmd
                _python_script(script)
            else:
                # Error case for '-m' without a module name
                print("\nError: -c flag requires a script.", file=sys.stderr)
        else:
            assert False, "Internal error"
    finally:
        shutdown()


