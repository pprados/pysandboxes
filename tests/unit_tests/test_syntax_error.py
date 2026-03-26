import logging
from pathlib import Path
from typing import Any, Generator, Mapping

from _pytest.logging import LogCaptureFixture  # type: ignore[import-untyped]

from pysandboxes import ConfigSyntaxError
from pysandboxes.py_sandbox import load_and_parse_config


def test_syntax_error(caplog: Generator[LogCaptureFixture, None, None]) -> None:
    """Check all possible syntax errors."""
    config_path = Path(__file__).parent / "syntax-error.profile"

    try:
        with caplog.at_level(logging.WARNING):  # type: ignore[attr-defined]
            extra: Mapping[str, Any] = {
                "os-sandbox": "error",
                "env": "abc",
                "bind": "",
            }
            load_and_parse_config(
                config_path,
                **extra,
            )
            assert 0, "Must raise an exception"
    except ConfigSyntaxError as e:
        cwd = str(Path.cwd())
        without_filename = [
            error.replace(cwd, ".").replace(
                "tests/unit_tests/syntax-error.profile", "syntax-error"
            )
            for error in e.errors
        ]
        # Check syntax error
        assert without_filename == [
            "<arg>: Detect a missing '=' in rule: env=abc.",
            "<arg>: Invalid os-sandbox 'error'.",
            "syntax-error(2) and syntax-error(3): Multiple os-sandbox parameters.",
            "<arg>: In 'bind=', source and destination must be separated with a comma.",
            "syntax-error(1): Invalid os-sandbox 'toto'.",
            "syntax-error(4): Invalid rule 'set-env=ERROR'",
            "syntax-error(5): In 'bind=.,not_exist', source and destination must exists and must be directories.",
            "syntax-error(6): In 'bind=not_exist,.', source and destination must exists and must be directories.",
            "syntax-error(7): In 'ro-bind=abc', source and destination must be separated with a comma.",
            "syntax-error(8): Invalid rule 'ignore-parameter'",
            "Port must be a positive value",
            "syntax-error(11): 'net=ERROR' has incorrect number of parts separated by '|'. Expected 5, got 1. "
            "Format: <DENY,ALLOW>|<TCP,UDP list or *>|<ip/mask>, *|<port list>|<IN, OUT>.",
            "syntax-error(12): 'net=ERROR|tcp|127.0.0.1/32|8000|IN' use an invalid action. Must be 'ALLOW' or 'DENY'.",
            "syntax-error(13): 'net=ALLOW||127.0.0.1/32|8000|IN' has empty socket specs.",
            "syntax-error(14): In 'net=ALLOW|any,tcp,udp|127.0.0.1/32|8000|IN', 'ANY' must be used alone, "
            "not combined with other specifiers.",
            "syntax-error(15): In 'net=ALLOW|*,tcp,udp|127.0.0.1/32|8000|IN', '*' must be used alone, "
            "not combined with other specifiers.",
            "syntax-error(16): 'net=ALLOW|toto|127.0.0.1/32/32|8000|IN' has unknown socket specifier 'TOTO'. "
            "Valid specifiers: any, TCP, UDP.",
            "syntax-error(17): In 'net=ALLOW|tcp||8000|IN', network part must be set.",
            "syntax-error(20): In 'net=ALLOW|tcp|0.0.0.0/0|a,b|IN', invalid port list.",
            "syntax-error(21): In 'net=ALLOW|tcp|0.0.0.0/0|*|', direction is not 'IN' or 'OUT'.",
            "syntax-error(26): Invalid value 'abc' for py-sandbox. Use true or false.",
            "syntax-error(27): Invalid value 'True' for 'learn'. Use the filename instead.",
            "syntax-error(28): Invalid rule 'invalide-rule'",
        ]
