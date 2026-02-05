import logging
from pathlib import Path

from pysandboxes.py_sandbox import read_and_parse_config


def test_syntax_error(caplog):
    """ Check all possible syntax errors."""
    config_path = Path(__file__).parent / "syntax-error.profile"

    try:
        with caplog.at_level(logging.WARNING):
            read_and_parse_config(config_path,
                                  extra_rules=[
                                      "os-sandbox=error",
                                      "set-env=abc",
                                      "bind=",
                                  ])
            assert 0, "Must raise an exception"
    except ValueError as e:
        cwd = str(Path.cwd())
        all_ignore = [record[2].replace(cwd, ".")
                      .replace("tests/unit_tests/syntax-error.profile",
                               "syntax-error")
                      for record in caplog.record_tuples[:-1]]
        # Check ignore rule
        assert all_ignore == [
            "syntax-error(8): Ignore invalid rule '--ignore-parameter'.",
            "syntax-error(13): Ignore invalid rule '--net=ALLOW|any,tcp,udp|127.0.0.1/32|8000|IN'.",
            "syntax-error(14): Ignore invalid rule '--net=ALLOW|*,tcp,udp|127.0.0.1/32|8000|IN'."
        ]
        # Check syntax error
        syntax_error = [
            msg.replace(cwd, "syntax-error").replace(
                "tests/unit_tests/syntax-error.profile", "syntax-error")
            for msg in
            caplog.record_tuples[-1][2].splitlines()[1:]]

        assert syntax_error == [
            "<arg>: Detect a missing '=' in rule: --set-env=abc.",
            "<arg>: Invalid os-sandbox 'error'.",
            '<arg>, syntax-error(1), syntax-error(2) and syntax-error(3): Multiple --os-sandbox parameters.',
            "<arg>: In '--bind=', source and destination must be separated with a comma.",
            "syntax-error(1): Invalid os-sandbox 'toto'.",
            "syntax-error(4): Detect a missing '=' in rule: --set-env=ERROR.",
            "syntax-error(5): In '--ro-bind=syntax-error,not_exist', source and destination must exists.",
            "syntax-error(6): In '--bind=not_exist,syntax-error', source and destination must exists.",
            "syntax-error(7): In '--ro-bind=abc', source and destination must be separated with a comma.",
            "syntax-error(10): '--net=ERROR' has incorrect number of parts separated by '|'. Expected 5, got 1. Format: <ALLOW, DENY>|<tcp,udp list or any>|<ip/mask>, *|<port list>|<IN, OUT>.",
            "syntax-error(11): '--net=ERROR|tcp|127.0.0.1/32|8000|IN' use an invalide action. Must be 'ALLOW' or 'DENY'.",
            "syntax-error(12): '--net=ALLOW||127.0.0.1/32|8000|IN' has empty socket specs.",
            "syntax-error(13): In '--net=ALLOW|any,tcp,udp|127.0.0.1/32|8000|IN', 'any' must be used alone, not combined with other specifiers.",
            "syntax-error(14): In '--net=ALLOW|*,tcp,udp|127.0.0.1/32|8000|IN', '*' must be used alone, not combined with other specifiers.",
            "syntax-error(15): '--net=ALLOW|toto|127.0.0.1/32/32|8000|IN' has unknown socket specifier 'toto'.Valid specifiers: any, tcp, udp.",
            "syntax-error(16): In '--net=ALLOW|tcp||8000|IN', network part must be set.",
            "syntax-error(18): In '--net=ALLOW|tcp|acme.acme|*|IN', invalid network specification.That does not resolve to any network.",
            "syntax-error(19): In '--net=ALLOW|tcp|0.0.0.0/0|a,b|IN', invalide port list.",
            "syntax-error(20): In '--net=ALLOW|tcp|0.0.0.0/0|*|', direction is not 'IN' or 'OUT'.",
            "syntax-error(24): In '--ro-bind=syntax-error,syntax-error/tests', invalidate another rule from 'syntax-error(22)'.",
            "syntax-error(25): Invalid value 'abc' for --py-sandbox. Use true or false."
        ]
