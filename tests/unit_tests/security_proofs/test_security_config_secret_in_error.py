# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
"""Security proof test for the configuration loader (AREA B of the cybedefend audit).

Marked run:    pytest tests/unit_tests/security_proofs/test_security_config_secret_in_error.py
Raw run:       pytest --runxfail tests/unit_tests/security_proofs/test_security_config_secret_in_error.py

``pysandboxes/tools.py::substitute_config_env_vars`` resolves every ``${VAR}`` reference in a rule
line, including one no guard ever recognises, before any guard gets a chance to parse it. A line
``parse_config`` (``pysandboxes/py_sandbox.py``) cannot match to any known directive -- a typo in
the key, a directive that does not exist, one guard rejects for its own reason -- falls through to
the catch-all at the end of ``parse_config``, which echoes the line *as substituted* into the
``ConfigSyntaxError`` it raises: ``f"{format_ruleref(invalide_rule)}: Invalid rule
{invalide_rule.rule!r}"``. A profile that forwards a secret with ``${...}`` syntax (the documented
way to keep a key out of the rule file, `README.md`'s `env=*_API_KEY=${*_API_KEY}` example) leaks
that secret in clear text the moment any other line near it fails to parse -- to whatever prints,
logs or returns this exception (``python-sb`` prints it to stderr; an application that surfaces
its own startup errors returns it to whoever triggered them).
"""

from pathlib import Path

import pytest  # type: ignore[import-untyped]

from pysandboxes.e import ConfigSyntaxError
from pysandboxes.py_sandbox import load_and_parse_config

SECRET = "sk-TOTALLY-SECRET-TOKEN-0000000000"  # noqa: S105 - a fixture value, not a real credential


def test_security_a_rejected_rule_does_not_echo_its_substituted_secret(tmp_path: Path) -> None:
    """An invalid rule's error must not disclose the value a ``${VAR}`` substitution put there.

    The misspelled directive below (``exposer-rw`` instead of ``expose-rw``) is not a directive
    any guard parses, so it survives every guard's ``parse_rules`` and reaches the catch-all that
    raises ``ConfigSyntaxError``. Its value is a plain ``${SECRET_TOKEN}`` reference, exactly the
    syntax the project's own documentation recommends for keeping a credential out of the rule
    file: the operator did everything the docs ask, and the secret still ends up in the exception.
    """
    config = tmp_path / ".py-sandboxes"
    config.write_text("py-sandbox=true\nos-sandbox=none\nlearn=false\nexposer-rw=${SECRET_TOKEN}\n")

    with pytest.raises(ConfigSyntaxError) as excinfo:
        load_and_parse_config(config_path=config, envs={"SECRET_TOKEN": SECRET})

    message = str(excinfo.value)
    assert SECRET not in message, f"the rejected rule's error discloses the substituted secret: {message!r}"
    assert "exposer-rw=${SECRET_TOKEN}" in message
