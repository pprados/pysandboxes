# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""
This module provides utilities for parsing the Python command line.

It is designed to separate standard CPython interpreter arguments from custom
arguments intended for the pysandbox environment, and from the actual command
(script, -c, or -m) to be executed.
"""

import argparse
import sys
from pathlib import Path

from pysandboxes.config import CONFIG_NAME
from pysandboxes.tools import find_config_for_module


def parse_python_cmd_line(
    args: list[str],
) -> tuple[list[str], list[str], list[str], Path]:
    """
    Parses the Python command line to separate CPython, sandbox, and command args.

    This function uses `argparse` to identify standard CPython command-line
    options. Any arguments not recognized by the parser are considered custom
    sandbox arguments. It also handles various help flags, printing the help
    message and exiting if any are present.

    Args:
        args: A list of command-line arguments from sys.argv[1:].

    Returns:
        A tuple containing:
        1. `python_parsed_args`: Standard CPython arguments.
        2. `sandboxes_args`: Custom arguments for the sandbox.
        3. `python_cmd`: The command to be executed and its arguments.
        4. `pysandboxes_config`: The path for configuration
    """

    class CustomHelpFormatter(argparse.HelpFormatter):
        """
        Custom argparse formatter to control help message width and add extra info.
        """

        def __init__(
            self,
            prog: str,
            indent_increment: int = 2,
            max_help_position: int = 10,
            width: int | None = None,
        ):
            """Initializes the custom formatter, setting a default width."""
            # We override the width here instead of in the parent class
            if width is None:
                width = 80  # Default width, change this as needed
            super().__init__(prog, indent_increment, max_help_position, width)
            # super().add_argument(SandboxAction())

        def format_help(self) -> str:
            """Appends additional argument info to the standard help message."""
            help = super().format_help()
            help += (
                "\n"
                "Arguments:\n"
                "file   : program read from script file\n"
                "-      : program read from stdin (default; interactive mode "
                "if a tty)\n"
                "arg ...: arguments passed to program in sys.argv[1:]\n"
            )
            return help

    long_params = [
        "--help",
        "--help-env",
        "--help-xoptions",
        "--help-all",
        "--check-hash-based-pycs",
    ]

    # Split args before '--', '-c', '-m'
    split_pos = -1
    for i, arg in enumerate(args):
        if arg in ("--", "-c", "-m"):
            split_pos = i
            break
    if split_pos == -1:
        # split with the first *.py parameter
        for i, arg in enumerate(args):
            if arg.endswith(".py"):
                split_pos = i
                break

    python_run_args = []
    if split_pos != -1:
        python_run_args = args[split_pos:]
        args = args[:split_pos]

    pysandboxes_config: Path = Path(CONFIG_NAME)
    module_mode = False
    if (len(python_run_args) >= 2 and python_run_args[0] == "-m"):
        module_mode=True

    for arg in args:
        if arg.startswith("--pysandboxes-config="):
            # Accept full name or relative name of the module
            _, pysandboxes_config_p = arg.split("=", maxsplit=1)
            pysandboxes_config = Path(pysandboxes_config_p)

    if ("/" not in str(pysandboxes_config) and module_mode):
        try:
            caller_module = python_run_args[1]
            if x := find_config_for_module(caller_module, str(pysandboxes_config)):
                pysandboxes_config = x
        except FileNotFoundError:
            pass  # Ignore

    sandboxes_args = [
        arg
        for arg in args
        if arg.startswith("--") and arg not in long_params
        and not arg.startswith("--pysandboxes-config=")
    ]
    args = [arg for arg in args if arg not in sandboxes_args]

    # Remove --pysandboxes-config. it's not a real parameter
    sandboxes_args = [
        arg for arg in sandboxes_args if not arg.startswith("--pysandboxes-config=")
    ]

    parser = argparse.ArgumentParser(
        prog="python-sb",
        description="Run a Python program in a SANBOX.",
        add_help=False,  # We'll add -h manually for full control
        formatter_class=CustomHelpFormatter,
    )
    parser.add_argument(
        "-h",
        "-?",
        "--help",
        action="store_true",
        help="Print a short description of all command line options and "
        "corresponding environment variables and exit.",
    )
    parser.add_argument(
        "--help-env",
        action="store_true",
        help="Print a short description of Python-specific environment "
        "variables and exit.",
    )
    parser.add_argument(
        "--help-xoptions",
        action="store_true",
        help="Print a description of implementation-specific -X options and exit.",
    )
    parser.add_argument(
        "--help-all",
        action="store_true",
        help="Print complete usage information and exit.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        help="Print the Python version number and exit.",
    )

    parser.add_argument(
        "-b",
        action="store_true",
        help="Issue a warning when converting bytes or bytearray to str without "
        "specifying encoding or comparing bytes or bytearray with str or bytes "
        "with int. Issue an error when the option is given twice (-bb).",
    )
    parser.add_argument(
        "-B",
        action="store_true",
        help="If given, Python won’t try to write .pyc files on the import of "
        "source modules. See also PYTHONDONTWRITEBYTECODE.",
    )
    parser.add_argument(
        "--check-hash-based-pycs",
        action="store_true",
        # default|always|never
        help="Control the validation behavior of hash-based .pyc files.",
    )
    parser.add_argument(
        "-d",
        action="store_true",
        help="Turn on parser debugging output (for expert only)",
    )
    parser.add_argument(
        "-E",
        action="store_true",
        help="Ignore all PYTHON* environment variables, e.g. PYTHONPATH and "
        "PYTHONHOME, that might be set.",
    )

    parser.add_argument(
        "-i", action="store_true", help="Enter interactive mode after execution."
    )
    parser.add_argument("-I", action="store_true", help="Run Python in isolated mode.")
    parser.add_argument(
        "-O",
        action="store_true",
        help="Remove assert statements and any code conditional on "
        "the value of __debug__.",
    )
    parser.add_argument(
        "-OO", action="store_true", help="Do -O and also discard docstrings. "
    )
    parser.add_argument(
        "-P",
        action="store_true",
        help="Don’t prepend a potentially unsafe path to sys.path",
    )
    parser.add_argument(
        "-q",
        action="store_true",
        help="Don’t display the copyright and version messages "
        "even in interactive mode.",
    )
    parser.add_argument("-R", action="store_true", help="Turn on hash randomization.")
    parser.add_argument(
        "-s",
        action="store_true",
        help="Don’t add the user site-packages directory to sys.path.",
    )
    parser.add_argument(
        "-S",
        action="store_true",
        help="Disable the import of the module site and the site-dependent "
        "manipulations of sys.path that it entails. ",
    )
    parser.add_argument(
        "-u",
        action="store_true",
        help="Force the stdout and stderr streams to be unbuffered. ",
    )
    parser.add_argument(
        "-v",
        action="store_true",
        help="Print a message each time a module is initialized, showing the "
        "place (filename or built-in module) from which it is loaded. ",
    )
    parser.add_argument(
        "-W",
        action="append",
        metavar="arg",
        dest="warnings",
        help="Warning control. Python’s warning machinery by default prints "
        "warning messages to sys.stderr.",
    )
    parser.add_argument(
        "-x",
        action="store_true",
        help="Skip first line of source, allowing use of non-Unix forms of #!.",
    )
    parser.add_argument(
        "-X",
        action="append",
        metavar="opt",
        dest="xoptions",
        help="Reserved for various implementation-specific options. ",
    )

    python_parsed = parser.parse_args(args)
    if python_parsed.help:
        # Add extra parameter before generate the help
        parser.add_argument(
            "--pysandboxes-config",
            action="store",
            help="Where to find the pysandboxes configuration.",
        )
        parser.add_argument(
            "--<sb-option>=<value>",
            action="store_true",
            dest="config",
            help="Add some Py-sandboxes parameters. They have priority.",
        )
        group = parser.add_mutually_exclusive_group()

        group.add_argument(
            "-m",
            action="store",
            metavar="mod",
            dest="module",
            help="Run library module as a script (terminates option list).",
        )
        group.add_argument(
            "-c",
            action="store",
            metavar="cmd",
            dest="command",
            help="Program passed in as a string.",
        )
        # TODO: https://docs.python.org/3.14/whatsnew/3.14.html#ast
        parser.print_help()
        sys.exit(0)

    return (args, sandboxes_args, python_run_args, pysandboxes_config)
