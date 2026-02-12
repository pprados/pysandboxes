import importlib
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Union, Set

from pysandboxes.learning import is_learning_mode, generate_config_from_learning
from pysandboxes.tools import set_is_in_sandbox
from ..all_rules import AllRules

logger = logging.getLogger(__name__)


def _debug_log():
    level = logging.WARNING  # FIX_RELEASE
    format = '%(levelname)-5s [%(process)d] %(name)s: %(message)s'
    logging.basicConfig(
        level=level,
        format=format
    )
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("aiohttp_sse_client.client").setLevel(logging.WARNING)
    logging.getLogger("Pysandboxes").setLevel(level)
    logging.getLogger("pysandboxes").setLevel(level)
    logging.getLogger("pysandboxes.remote.firejail_daemon").setLevel(level)


def _python_interactive(
        all_rules: AllRules,
        ban: bool,
) -> int:
    exit_msg = None
    term = os.environ.get('TERM')
    if (
            sys.stdout.isatty() and
            (
                    (term and ('color' in term or '256' in term or 'true' in term)) or
                    (sys.platform == 'win32' and 'ANSICON' in os.environ)
            )
    ):
        BOLD = '\033[1m'
        RED = '\033[1m\033[31m'
        RESET = '\033[0m'
    else:
        BOLD = '*** '
        RED = ''
        RESET = ' ***'

    if all_rules.learn:
        sb_mode = (f'{BOLD}API calls are LEARNED and saved in '
                   f'{str(all_rules.learning_path)!r} at the '
                   f'end of the session.{RESET}\n')
        exit_msg = f"Save rules to {str(all_rules.learning_path)!r}"
    elif all_rules.use_py_sandbox:
        sb_mode = (f'{BOLD}APIs are LIMITED according to the rules in '
                   f'{str(all_rules.learning_path)!r} '
                   )
        if all_rules.os_sandbox != "subprocess":
            sb_mode += f'and by the os-sandbox={all_rules.os_sandbox!r}'
        sb_mode += f"{RESET}\n"
    else:
        sb_mode = (f'*** APIs are LIMITED only by the os-sandbox '
                   f'of type {all_rules.os_sandbox!r} ***\n'
                   )
    banner = (
        f'{RED}SANDBOXES Python{RESET} {sys.version} on {sys.platform}\n'
        f'{sb_mode}'
        'Type "help", "copyright", "credits" or "license" for more information.'
    )
    prefix = "\u26A0 "

    try:
        # Try to import and use IPython for a better REPL experience
        from types import ModuleType

        # Hack for IPython
        sys.modules["__main__"] = ModuleType(name="__main__")
        import IPython
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
        if ban:
            print(banner)
        print(
            f"IPython {IPython.__version__} -- An enhanced Interactive Python. "
            f"Type '?' for help.")
        IPython.start_ipython(argv=[], user_ns=None,
                              config=c,
                              )
    except ImportError:
        import traceback
        traceback.print_exc()
        # Fallback to the standard Python REPL if IPython is not installed
        import code

        # Create a banner for the standard REPL
        if hasattr(sys, 'ps1'):
            sys.ps1 = prefix + sys.ps1
        else:
            sys.ps1 = prefix + ">>> "

        # Start the standard interactive console
        try:
            code.interact(banner=banner if ban else "",
                          exitmsg=exit_msg,
                          # When self.local_exit is True, we overwrite the builtins so
                          # exit() and quit() only raises SystemExit and we can catch that
                          # to only exit the interactive shell
                          local_exit=True,
                          )
        except SystemExit as e:
            pass
    return 0


def _python_module(all_rules: AllRules,
                   mod_name: str) -> int:
    import runpy
    runpy.run_module(mod_name, run_name="__main__")
    if sys.flags.inspect:
        return _python_interactive(all_rules=all_rules, ban=False)
    return 0


def _python_script(
        all_rules: AllRules,
        script: Path,
        args: List[str]
) -> int:
    try:
        script_body = script.read_text()
        sys.argv = [str(script)] + args
        exec(script_body)
        if sys.flags.inspect:
            return _python_interactive(all_rules=all_rules, ban=False)
        return 0
    except FileNotFoundError:
        print(f"python: can't open file {str(script)!r}: "
              f"[Errno 2] No such file or directory", file=sys.stderr)
        return 2


def _python_command(
        all_rules: AllRules,
        script_body: str,
        args: List[str]
) -> int:
    sys.argv = args
    exec(script_body)
    if sys.flags.inspect:
        return _python_interactive(all_rules=all_rules, ban=False)
    return 0


def convert_extra_rules(args: List[str]) -> Dict[str, Union[str, Set[str]]]:
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
) -> int:
    try:
        _debug_log()
        set_is_in_sandbox(True)
        if not len(python_cmd):
            _python_interactive(all_rules, True)
        elif python_cmd[0] == '-m':
            # Case: Execute a module
            if len(python_cmd) > 1:
                mod_name = python_cmd[1]
                python_cmd.pop(0)  # Remove -m
                python_cmd.pop(0)  # Remove module name
                spec = importlib.util.find_spec(mod_name)
                print(f"{mod_name=}")
                print(f"{spec=}")
                if spec:
                    sys.argv = [spec.origin] + python_cmd
                else:
                    sys.argv = [""] + python_cmd
                return _python_module(all_rules, mod_name)
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
                return _python_command(all_rules, script_body, python_cmd)
            else:
                print("Argument expected for -c option\n"
                      "usage: python-sb [option] ... [-c cmd | -m mod | file | -] [arg] ...\n"
                      "Try `python-sb -h' for more information.\n",
                      file=sys.stderr)
        else:
            # Run a script
            _python_script(all_rules, Path(python_cmd[0]), python_cmd[1:])
        return 0
    finally:
        if is_learning_mode():
            generate_config_from_learning()
