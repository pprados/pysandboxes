import logging
from pathlib import Path
from typing import Any, Generator, Mapping

import pytest
from _pytest.logging import LogCaptureFixture  # type: ignore[import-untyped]

from pysandboxes import ConfigSyntaxError
from pysandboxes.py_sandbox import load_and_parse_config


def test_syntax_error(caplog: Generator[LogCaptureFixture, None, None], monkeypatch: pytest.MonkeyPatch) -> None:
    """Check all possible syntax errors."""
    monkeypatch.setattr("sys.platform", "linux")
    config_path = Path(__file__).parent / "syntax-error.profile"

    cwd = str(Path.cwd())
    try:
        with caplog.at_level(logging.WARNING):  # type: ignore[attr-defined]
            extra: Mapping[str, Any] = {
                "os-sandbox": "error",
                "env": "abc",
                "expose-rw": "",
            }
            load_and_parse_config(
                config_path,
                envs={"PWD": cwd},
                **extra,
            )
            assert 0, "Must raise an exception"
    except ConfigSyntaxError as e:
        without_filename = [
            error.replace(cwd, ".").replace("tests/unit_tests/syntax-error.profile", "syntax-error")
            for error in e.errors
        ]
        # Check syntax error
        assert without_filename == [
            "<arg>: Detect a missing '=' in rule: env=abc.",
            "<arg>: Invalid os-sandbox 'error'.",
            "syntax-error(2) and syntax-error(3): Multiple os-sandbox parameters.",
            "<arg>: In 'expose-rw=', path must be set.",
            "syntax-error(1): Invalid os-sandbox 'toto'.",
            "syntax-error(4): Invalid rule 'set-env=ERROR'",
            "syntax-error(5): In 'expose-ro=.,not_exist', expected a single path (no comma).",
            "syntax-error(6): In 'expose-rw=not_exist,.', expected a single path (no comma).",
            "syntax-error(7): In 'expose-ro=abc', path 'abc' must exist.",
            "syntax-error(8): Invalid rule 'ignore-parameter'",
            "syntax-error(9): Port must be a positive value",
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
            "syntax-error(23): In 'expose-rw=.,./tests', expected a single path (no comma).",
            "syntax-error(24): In 'expose-rw=.,./tests/unit_tests', expected a single path (no comma).",
            "syntax-error(25): In 'expose-ro=.,./tests', expected a single path (no comma).",
            "syntax-error(26): Invalid value 'abc' for py-sandbox. Use true or false.",
            "syntax-error(27): Invalid value 'True' for 'learn'. Use the filename instead.",
            "syntax-error(28): Invalid rule 'invalide-rule'",
            "syntax-error(29): In 'eval-syntax=', empty target.",
            "syntax-error(30): In 'eval-syntax=loop,DENY:Try', DENY: applies to a whole line; "
            "put `eval-syntax=DENY:Try` on a line of its own.",
            "syntax-error(31): In 'eval-syntax=For*', a pattern is not accepted on eval-syntax: "
            "the vocabulary is finite.",
            "syntax-error(32): In 'eval-syntax=NotANode', unknown syntax token 'NotANode'.",
            "syntax-error(34): In 'eval-timeout=6s', eval-timeout is set twice in this profile "
            "(already at line 33): a scalar is not a set.",
            "syntax-error(35): In 'eval-unknown=1', unknown key 'eval-unknown'.",
            "syntax-error(36): In 'eval-namespace=open', eval-namespace: unknown mode 'open', "
            "expected one of ['adaptive', 'closed', 'caller'].",
            "syntax-error(37): In 'eval-timeout:other=abc', could not convert string to float: 'abc'",
            "syntax-error(38): In 'eval-max-nodes=abc', invalid literal for int() with base 10: 'abc'",
            "syntax-error(39): In 'eval-max-depth=DENY:3', "
            "eval-max-depth: `DENY:` and patterns apply to list keys only.",
        ]
