# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
import builtins
import code
import contextlib
import importlib
import importlib.util
import logging
import os
import runpy
import signal
import sys
import traceback
from pathlib import Path
from types import FrameType, ModuleType
from typing import Any, Dict, Iterator, List, Set

from pysandboxes.learning import (
    generate_config_from_learning,
    is_learning_mode,
    set_learning_mode,
    set_learning_path,
)

from ..all_rules import AllRules
from ..e import RuleApiPermissionError, SandBoxError
from ..guard_api import is_allowed
from ..lifecycle import arm
from ..main_logger import config_log

logger = logging.getLogger(__name__)

# Captured at import time, which main_sandbox.py performs before
# activate_sandboxes(), so these are the unpatched builtins. This is the
# framework's own exemption from the dynamic-code category: running the user's
# script IS python-sb's job, and requiring every profile to grant
# `python-api=ALLOW:dynamic-code` so the framework can start would be a defect
# by omission, not a safeguard. The exemption is by call site, never by
# disabling the category.
#
# The ambient exemption does not cover this: in a development checkout this
# file is neither under the stdlib nor under site-packages, so it is guarded
# like any application file.
_RAW_EXEC = exec
_RAW_EVAL = eval
_RAW_COMPILE = compile


@contextlib.contextmanager
def raw_builtins() -> Iterator[None]:
    """Restore the unpatched eval/exec/compile for the duration of the block.

    The interactive console executes what the developer types, through
    IPython's run_cell or code.interact, both of which reach builtins.compile
    and builtins.exec. A REPL is unguarded code execution by definition, so
    this grants no privilege the prompt did not already have, while the file,
    socket, import and environment rules still hold.

    Yields:
        None, with the three builtins restored for the block.
    """
    import builtins

    saved = {name: getattr(builtins, name) for name in ("eval", "exec", "compile")}
    builtins.eval, builtins.exec, builtins.compile = _RAW_EVAL, _RAW_EXEC, _RAW_COMPILE
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(builtins, name, value)


def _debug_log() -> None:
    sandbox_level = logging.DEBUG
    uvicorn_log_level = logging.ERROR
    config_log(sandbox_level)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(uvicorn_log_level)
    logging.getLogger("uvicorn.error").setLevel(uvicorn_log_level)
    logging.getLogger("aiohttp_sse_client.client").setLevel(uvicorn_log_level)
    logging.getLogger("Pysandboxes").setLevel(logging.INFO)
    logging.getLogger("pysandboxes").setLevel(sandbox_level)
    logging.getLogger("pysandboxes.guard_import").setLevel(logging.INFO)
    logging.getLogger("pysandboxes.remote.firejail_daemon").setLevel(sandbox_level)


def _register_signals_handlers() -> None:
    # Windows has no SIGQUIT
    register_signal = tuple(getattr(signal, name) for name in ("SIGINT", "SIGTERM", "SIGQUIT") if hasattr(signal, name))

    signals = {s: signal.getsignal(s) for s in register_signal}
    saved: set[bool] = set()

    def signal_handler(
        signum: int,
        frame: FrameType | None,
    ) -> Any | int | signal.Handlers:
        """
        Handles termination signals for the parent process.
        It will save the rules before exiting itself.

        Stays installed and delegates to the original handler instead
        of restoring it: the ``saved`` set already makes the save
        happen once, so re-registering from inside a handler would buy
        nothing and would mutate the handler table at delivery time.
        """
        logger.info("Pysandboxes: Catch signal %s.", signum)
        handler = signals[signal.Signals(signum)]
        if not saved:
            saved.add(True)
            generate_config_from_learning()  # Save learning rules, once
        if callable(handler):
            return handler(signum, frame)
        return None

    for s in signals.keys():
        signal.signal(signal.Signals(s), signal_handler)


def _before_user_code() -> None:
    """The single arming point of the ``python-sb`` entry point.

    Registers the signal handlers first, so a SIGTERM arriving during user
    code still saves the learned rules, then arms. Not hoisted into
    :func:`python_in_sb` itself: the ``-m`` branch resolves the module spec
    before running it, and arming beforehand would charge that lookup to the
    user's ``python-import`` rules.
    """
    _register_signals_handlers()
    arm()


def _python_interactive(
    all_rules: AllRules,
    ban: bool,
) -> int:
    _before_user_code()
    exit_msg = None
    term = os.environ.get("TERM")
    if sys.stdout.isatty() and (
        (term and ("color" in term or "256" in term or "true" in term))
        or (sys.platform == "win32" and "ANSICON" in os.environ)
    ):
        BOLD = "\033[1m"
        RED = "\033[1m\033[31m"
        RESET = "\033[0m"
    else:
        BOLD = "*** "
        RED = ""
        RESET = " ***"

    if all_rules.learn:
        conf_path = all_rules.learning_path
        try:
            conf_path = conf_path.relative_to(Path.cwd())
        except ValueError:
            pass
        sb_mode = (
            f"{BOLD}API calls are LEARNED and saved in " f"{str(conf_path)!r} at the " f"end of the session.{RESET}\n"
        )
        exit_msg = f"Save rules to {str(all_rules.learning_path)!r}"
    elif all_rules.use_py_sandbox:
        sb_mode = (
            f"{BOLD}APIs are LIMITED according to the rules in "
            f"{str(all_rules.learning_path.absolute().relative_to(Path().absolute()))!r} "
        )
        if all_rules.os_sandbox != "subprocess":
            sb_mode += f"and by the os-sandbox={all_rules.os_sandbox!r}"
        sb_mode += f"{RESET}\n"
    else:
        sb_mode = f"*** APIs are LIMITED only by the os-sandbox " f"of type {all_rules.os_sandbox!r} ***\n"
    banner = (
        f"{RED}SANDBOXES Python{RESET} {sys.version} on {sys.platform}\n"
        f"{sb_mode}"
        'Type "help", "copyright", "credits" or "license" for more information.'
    )
    prefix = "\u26a0 "
    banner_shown = False

    with raw_builtins():
        try:
            # IPython starts a history-saving thread, and prompt_toolkit a
            # stdout-proxy thread on every prompt, so it cannot run without the
            # "threads" door. Refuse up front rather than let it fail halfway
            # through initialisation. Learning mode still tries it, so the rules
            # get recorded.
            _door, _category = "threading.Thread.start", "threads"
            if not is_learning_mode() and not is_allowed(_door):
                raise RuleApiPermissionError(_door, _category)

            # Try to import and use IPython for a better REPL experience
            # Hack for IPython
            sys.modules["__main__"] = ModuleType(name="__main__")

            import IPython
            from traitlets.config import get_config  # type: ignore

            c = get_config()

            # Update the prompt
            from IPython.terminal.prompts import Prompts

            class CustomPrompts(Prompts):
                def in_prompt_tokens(self) -> List[Any]:
                    result = super().in_prompt_tokens()
                    full_prompt = prefix + result[2][1]
                    result[2] = result[2][0], full_prompt
                    self.shell.prompt_length = len(full_prompt)  # type: ignore[attr-defined]
                    return result

            c.TerminalInteractiveShell.prompts_class = CustomPrompts

            c.TerminalIPythonApp.display_banner = False
            # c.InteractiveShellApp.exit_msg=exit_msg
            if ban:
                print(banner)
                banner_shown = True
            print(
                f"IPython {getattr(IPython, '__version__', 'unknown')} -- An enhanced Interactive Python. "
                f"Type '?' for help."
            )
            IPython.start_ipython(  # type: ignore[attr-defined]
                argv=[],
                user_ns=None,
                config=c,
            )
        except (ImportError, SandBoxError) as err:
            if isinstance(err, ImportError):
                traceback.print_exc()
            else:
                # IPython needs more than the plain REPL: threads for its history
                # saver and the prompt_toolkit stdout proxy, and a writable profile
                # directory. A rule refusal there is a configuration choice, not a
                # crash: name the door and keep the REPL that does not need it.
                print(f"{err}\nFalling back to the standard Python REPL.", file=sys.stderr)
            # Fallback to the standard Python REPL if IPython is not installed
            # Create a banner for the standard REPL
            if hasattr(sys, "ps1"):
                sys.ps1 = prefix + getattr(sys, "ps1")  # noqa: B009
            else:
                sys.ps1 = prefix + ">>> "

            # Start the standard interactive console
            try:
                extra: dict[str, Any] = {}
                if sys.version_info[:2] >= (3, 13):
                    extra = {"local_exit": True}
                code.interact(
                    banner=banner if ban and not banner_shown else "",
                    exitmsg=exit_msg,
                    # When self.local_exit is True, we overwrite the builtins so
                    # exit() and quit() only raises SystemExit and we can catch that
                    # to only exit the interactive shell
                    **extra,
                )
            except SystemExit:
                pass  # Ignore and continue
    return 0


def _python_module(all_rules: AllRules, mod_name: str) -> int:
    _before_user_code()
    runpy.run_module(mod_name, run_name="__main__")
    if sys.flags.inspect:
        return _python_interactive(all_rules=all_rules, ban=False)
    return 0


def _main_globals(file: str | None) -> dict:
    """The namespace CPython gives to ``__main__``.

    One mapping, used as both globals and locals: ``exec(source)`` with no
    explicit namespace takes the caller's ``globals()`` and ``locals()``, which
    here are two different dicts. The script's own assignments would land in
    the caller's locals while the functions it defines capture this module's
    globals, so a script function reading a script global raised ``NameError``.
    """
    namespace = {
        "__name__": "__main__",
        "__builtins__": builtins,
        "__doc__": None,
        "__package__": None,
        "__spec__": None,
    }
    if file is not None:
        namespace["__file__"] = file
    return namespace


def _python_script(all_rules: AllRules, script: Path, args: List[str]) -> int:
    try:
        _before_user_code()
        script_body = script.read_text()
        sys.argv = [str(script)] + args
        # Runs the user script by design; the OS sandbox isolates it.
        # Compiled against the real path so a traceback names the user's file.
        _RAW_EXEC(_RAW_COMPILE(script_body, str(script), "exec"), _main_globals(str(script)))
        if sys.flags.inspect:
            return _python_interactive(all_rules=all_rules, ban=False)
        return 0
    except FileNotFoundError:
        print(
            f"python: can't open file {str(script)!r}: " f"[Errno 2] No such file or directory",
            file=sys.stderr,
        )
        return 2


def _python_command(all_rules: AllRules, script_body: str, args: List[str]) -> int:
    _before_user_code()
    sys.argv = args
    # Runs the user script by design; the OS sandbox isolates it.
    # No __file__: CPython does not set one for ``python -c`` either.
    _RAW_EXEC(_RAW_COMPILE(script_body, "<string>", "exec"), _main_globals(None))
    if sys.flags.inspect:
        return _python_interactive(all_rules=all_rules, ban=False)
    return 0


def _inject_pytest_color_yes(pytest_argv: List[str]) -> None:
    """Force pytest ANSI when stdout is not a TTY (same effect as PY_COLORS=1, no env var)."""
    for arg in pytest_argv:
        if arg.startswith("--color="):
            return
    pytest_argv.insert(0, "--color=yes")


def convert_extra_rules(args: List[str]) -> Dict[str, Set[str]]:
    result: Dict[str, Set[str]] = {}
    for rule in args:
        assert rule.startswith("--")
        rule = rule[2:]
        if "=" in rule:
            key, val = rule.split("=", maxsplit=1)
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
        set_learning_path(all_rules.learning_path)  # TODO: may be duplicate of main_sandbox
        set_learning_mode(all_rules.learn)
        if not len(python_cmd):
            _python_interactive(all_rules, True)
        elif python_cmd[0] == "-m":
            # Case: Execute a module
            if len(python_cmd) > 1:
                mod_name = python_cmd[1]
                python_cmd.pop(0)  # Remove -m
                python_cmd.pop(0)  # Remove module name
                if mod_name == "pytest":
                    _inject_pytest_color_yes(python_cmd)
                spec = importlib.util.find_spec(mod_name)
                if spec and spec.origin is not None:
                    sys.argv = [spec.origin] + python_cmd
                else:
                    sys.argv = [""] + python_cmd
                return _python_module(all_rules, mod_name)
            else:
                # Error case for '-m' without a module name
                print(
                    "Argument expected for -m option\n"
                    "usage: python-sb [option] ... "
                    "[-c cmd | -m mod | file | -] [arg] ...\n"
                    "Try `python-sb -h' for more information.\n",
                    file=sys.stderr,
                )

        elif python_cmd[0] == "-c":
            # Case: Execute a command
            if len(python_cmd) > 1:
                script_body = python_cmd[1]
                python_cmd.pop(1)
                return _python_command(all_rules, script_body, python_cmd)
            else:
                print(
                    "Argument expected for -c option\n"
                    "usage: python-sb [option] ... "
                    "[-c cmd | -m mod | file | -] [arg] ...\n"
                    "Try `python-sb -h' for more information.\n",
                    file=sys.stderr,
                )
        else:
            # Run a script
            return _python_script(all_rules, Path(python_cmd[0]), python_cmd[1:])
        return 0
    finally:
        if is_learning_mode():
            generate_config_from_learning()
