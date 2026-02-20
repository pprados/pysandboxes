import argparse
import sys
from typing import List, Optional, Tuple


def _split_python_cmd(args: List[str]) -> Tuple[List[str], List[str]]:
    for idx, arg in enumerate(args):
        if arg in ("-c", "-m") or not arg.startswith("-"):
            python_args, other_args = args[:idx], args[idx:]
            break
    else:
        python_args, other_args = args, []
    return python_args, other_args


def parse_python_cmd_line(args: List[str]) -> Tuple[List[str], List[str], List[str]]:
    # Split the command line in 3 parts:
    # - cpython parameter,
    # - pysandbox extra parameters,
    # - cpython command (-c ..., -i, acme.py, ...)
    #
    # If the parameter ask the help, print it and exit

    # Split args before and after python command
    python_args, python_cmd = _split_python_cmd(args)

    # Parse python argument
    # class SandboxAction(argparse.Action):
    #     def __init__(self,
    #                  option_strings: Sequence[str],
    #                  dest: str,
    #                  # type:Callable[[str], _T] | FileType | None=None,
    #                  # nargs:int | _NArgsStr | _SUPPRESS_T | None=None,
    #                  # const:Any=None,
    #                  # default:Any=None,
    #                  # choices:Iterable[_T] | None=None,
    #                  # required:bool=False,
    #                  # metavar:str | tuple[str, ...] | None=None,
    #                  # help:str=None,
    #                  # deprecated:bool=False
    #                  ):
    #         super().__init__(option_strings="OPTOIN_STRING",
    #                          dest="DEST",
    #                          required=False,
    #                          help=None,
    #                          deprecated=False,
    #                          metavar=argparse._deprecated_default,
    #                          )
    #
    #     def __call__(self, *args, **kwargs):
    #         print(f"Program Version: {self.version}")

    class CustomHelpFormatter(argparse.HelpFormatter):
        """A custom formatter that wraps help messages at a specified width."""

        def __init__(
            self,
            prog: str,
            indent_increment: int = 2,
            max_help_position: int = 10,
            width: Optional[int] = None,
        ):
            # We override the width here instead of in the parent class
            if width is None:
                width = 80  # Default width, change this as needed
            super().__init__(prog, indent_increment, max_help_position, width)
            # super().add_argument(SandboxAction())

        def format_help(self) -> str:
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
        action="store",
        metavar="opt",
        dest="xoptions",
        help="Reserved for various implementation-specific options. ",
    )

    python_parsed, sandboxes_args = parser.parse_known_args(args=python_args)
    python_parsed_args = [arg for arg in python_args if arg not in sandboxes_args]

    if python_parsed.help:
        # Add extra parameter before generate the help
        parser.add_argument(
            "--<sb-option>=<value>",
            action="store_true",
            dest="config",
            help="Add some Py-sandboxes parameters.",
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

        parser.print_help()
        sys.exit(0)

    return python_parsed_args, sandboxes_args, python_cmd
