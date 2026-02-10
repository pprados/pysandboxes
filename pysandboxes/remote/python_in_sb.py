import importlib
import logging
import sys
from pathlib import Path
from typing import List, Dict, Union, Set

from pysandboxes.learning import is_learning_mode, generate_config_from_learning
from ..all_rules import AllRules

logger = logging.getLogger(__name__)


def _debug_log():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(levelname)-5s [%(process)d] %(name)s: %(message)s'
    )
    logging.getLogger("pysandboxes").setLevel(logging.WARNING)
    logging.getLogger("Pysandboxes").setLevel(
        logging.INFO)  # TODO: with parameter level ?


def _python_interactive(
        all_rules: AllRules,
):
    # TODO: le envs final doit être injecté proprement
    exit_msg = None
    if all_rules.learning:
        sb_mode = (f'*** API calls are LEARNED and saved in '
                   f'{str(all_rules.learning_path)!r} at the '
                   f'end of the session. ***\n')
        exit_msg = f"Save rules to {str(all_rules.learning_path)!r}"
    elif all_rules.use_py_sandbox:
        sb_mode = (f'*** APIs are LIMITED according to the rules in '
                   f'{str(all_rules.learning_path)!r} '
                   f'and by the os-sandbox of type {all_rules.os_sandbox!r} ***\n'
                   )
    else:
        sb_mode = (f'*** APIs are LIMITED only by the os-sandbox '
                   f'of type {all_rules.os_sandbox!r} ***\n'
                   )
    banner = (
        f'SANDBOXES Python {sys.version} on {sys.platform}\n'
        f'{sb_mode}'
        'Type "help", "copyright", "credits" or "license" for more information.'
    )
    prefix = "\u26A0 "

    try:
        # Try to import and use IPython for a better REPL experience
        from types import ModuleType

        # Hack for IPython
        sys.modules["__main__"] = ModuleType("__main__")
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
        # c.InteractiveShellApp.exit_msg=exit_msg
        print(banner)
        print(
            f"IPython {IPython.__version__} -- An enhanced Interactive Python. "
            f"Type '?' for help.")
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
        try:
            code.interact(banner=banner,
                          exitmsg=exit_msg,
                          # When self.local_exit is True, we overwrite the builtins so
                          # exit() and quit() only raises SystemExit and we can catch that
                          # to only exit the interactive shell
                          local_exit=True,
                          )
        except SystemExit as e:
            pass


def _python_module(mod_name: str) -> int:
    import runpy
    runpy.run_module(mod_name, run_name="__main__")
    return 0


def _python_script(script: Path,
                   args: List[str]
                   ) -> int:
    try:
        script_body = script.read_text()
        sys.argv = [str(script)] + args
        exec(script_body)
        return 0
    except FileNotFoundError:
        print(f"python: can't open file {str(script)!r}: "
              f"[Errno 2] No such file or directory", file=sys.stderr)
        return 2


def _python_command(script_body: str,
                    args: List[str]
                    ) -> int:
    sys.argv = args
    exec(script_body)
    return 0


def _convert_extra_rules(args: List[str]) -> Dict[str, Union[str, Set[str]]]:
    result = {}
    for rule in args:
        assert rule.startswith("--")
        rule = rule[2:]
        if '=' in rule:
            key, val = rule.split('=', maxsplit=1)
        else:
            key, val = rule, ""  # Empty by default
        if key in result:
            result[key].add(val)
        else:
            result[key] = {val}
    return result


def python_in_sb(
        all_rules: AllRules,
        python_cmd: List[str],
):
    try:
        if not len(python_cmd) or python_cmd[0] == "-i" or python_cmd[0] == "-":
            _python_interactive(all_rules)
        elif python_cmd[0] == '-m':
            # Case: Execute a module
            if len(python_cmd) > 1:
                mod_name = python_cmd[1]
                python_cmd.pop(0)  # Remove -m
                python_cmd.pop(0)  # Remove module name
                spec = importlib.util.find_spec(mod_name)
                sys.argv = [spec.origin] + python_cmd
                return _python_module(mod_name)
            else:
                # Error case for '-m' without a module name
                print("Argument expected for -m option\n"
                      "usage: python-sb [option] ... [-c cmd | -m mod | file | -] [arg] ...\n"
                      "Try `python-sb -h' for more information.\n",
                      file=sys.stderr)

        elif python_cmd[0] == '-c':
            # Case: Execute a comand
            if len(python_cmd) > 1:
                script_body = python_cmd[1]
                python_cmd.pop(1)
                return _python_command(script_body, python_cmd)
            else:
                print("Argument expected for -c option\n"
                      "usage: python-sb [option] ... [-c cmd | -m mod | file | -] [arg] ...\n"
                      "Try `python-sb -h' for more information.\n",
                      file=sys.stderr)
        else:
            # Run a script
            _python_script(Path(python_cmd[0]), python_cmd[1:])
    finally:
        if is_learning_mode():
            generate_config_from_learning()


if __name__ == "__main__":  # FIXME: for debug only
    from ..all_rules import EmptyRules

    all_rules = EmptyRules
    python_in_sb(all_rules,
                 [],
                 )
