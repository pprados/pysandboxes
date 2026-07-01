# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""What pysandboxes enforces on the two tools Agno exposes to the model.

Agno takes plain functions as tools, so the wrapper handed to the agent is an
ordinary function delegating to a module-level ``_``-prefixed one carrying
`@sandbox` -- the indirection D7 of the design spec asks for. The tests call
the inner function, which is what the wrapper ends up calling, and then the
wrapper itself, which is what the model reaches.

Scenario A, the negative control, runs in a separate process. A baseline
profile leaves ``is_in_sandbox()`` true behind it, so an armed block running
afterwards in the same process short-circuits and silently reproduces the
baseline's results -- which is how a blocking test ends up unable to fail.

Scenarios B and C run armed, against the real network. Nothing is mocked: a
mocked transport proves the mock, not the rule.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from pysandboxes import sandbox_denials, sandboxes

from agno_demo.tools import (
    _evaluate_expression,
    _fetch_webpage,
    evaluate_expression,
    fetch_webpage,
)

SAMPLE_ROOT = Path(__file__).parent.parent
# One profile per mode, each learned in its own. They are not
# interchangeable: the partial profile has to allow the bridge that runs
# inside the sandbox with the tool (fastapi, uvicorn, starlette...), and the
# complete one has to allow the framework's own dispatch, which in partial mode
# stays in the parent. Sharing one profile would grant each mode
# the other's privileges for nothing.
CONFIG = SAMPLE_ROOT / ".py-sandboxes"
CONFIG_COMPLETE = SAMPLE_ROOT / ".py-sandboxes-complete"

# Host the learned profile allows.
ALLOWED_URL = "https://www.google.com/"
# Real, resolvable host deliberately absent from net=ALLOW: a real name keeps
# the refusal attributable to the rule instead of to an NXDOMAIN.
DENIED_URL = "https://example.com/"

# Reaches Popen through the subclass tree, which an emptied __builtins__ does
# not hide. The tool is a plain eval() on purpose: whatever stops this is the
# sandbox, not a parser.
POPEN_ESCAPE = (
    "[c for c in ().__class__.__base__.__subclasses__() if c.__name__=='Popen'][0](['/bin/echo','pwned'])"
)


def armed_kwargs() -> dict[str, object]:
    return {"sandboxes_config": CONFIG, "py_sandbox": "true", "os_sandbox": "subprocess"}


def test_scenario_a_the_escape_succeeds_without_the_sandbox() -> None:
    """Without pysandboxes the malicious expression runs. Otherwise C proves nothing."""
    # subprocess is imported first because the escape walks the subclass tree
    # and Popen has to be loaded -- as it is in the real process, httpx and
    # agno pulling it in long before a model says anything.
    script = f"import subprocess; print(eval({POPEN_ESCAPE!r}, {{'__builtins__': {{}}}}, {{}}))"
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=SAMPLE_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert "Popen" in result.stdout, result.stdout


def test_scenario_b2_an_allowed_host_is_reached() -> None:
    with sandboxes(**armed_kwargs()):
        page = _fetch_webpage(ALLOWED_URL)

    assert page.strip(), "the allowed host returned nothing"


def test_scenario_b1_a_host_outside_the_rules_is_refused() -> None:
    """The refusal is attributable, which asserting on the message would not be."""
    with sandboxes(**armed_kwargs()):
        with pytest.raises(Exception) as caught:
            _fetch_webpage(DENIED_URL)

    denials = sandbox_denials(caught.value)
    assert denials, f"no denial reported, only {caught.value!r}"
    assert any("DENIED" in denial for denial in denials), denials


def test_the_expression_tool_still_computes() -> None:
    with sandboxes(**armed_kwargs()):
        assert _evaluate_expression("2*(3+4)") == 14


def test_scenario_c_the_malicious_expression_is_confined() -> None:
    """The escape of scenario A reaches Popen and is refused there, by the API guard.

    Not by the import guard: python-import=subprocess cannot be removed, since
    httpx and agno load it themselves.
    """
    with sandboxes(**armed_kwargs()):
        with pytest.raises(Exception) as caught:
            _evaluate_expression(POPEN_ESCAPE)

    denials = sandbox_denials(caught.value)
    assert denials, f"no denial reported, only {caught.value!r}"
    assert any("process-exec" in denial for denial in denials), denials


def test_the_wrappers_report_the_rule_to_the_model() -> None:
    """A model gets text, so the refusal has to be legible in it.

    This also exercises the D7 indirection end to end: calling the wrapper has
    to reach the sandboxed inner function through the bridge, which resolves it
    by `module:qualname`.
    """
    with sandboxes(**armed_kwargs()):
        refused_fetch = fetch_webpage(DENIED_URL)
        refused_eval = evaluate_expression(POPEN_ESCAPE)
        allowed_eval = evaluate_expression("2*(3+4)")

    assert "refused by the sandbox" in refused_fetch, refused_fetch
    assert "DENIED" in refused_fetch, refused_fetch
    assert "process-exec" in refused_eval, refused_eval
    assert allowed_eval == "14.0", allowed_eval


@pytest.mark.parametrize("profile", [CONFIG, CONFIG_COMPLETE], ids=["partial", "complete"])
def test_the_profile_is_a_whitelist(profile: Path) -> None:
    """Guard the two ways this demonstration has silently died before."""
    active = [
        line.strip()
        for line in profile.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert "python-import=*" not in active, "a wildcard import rule voids the whitelist"
    assert not [line for line in active if line.startswith("python-api=ALLOW:process-exec")], (
        "allowing process-exec would void scenario C"
    )
    assert not [line for line in active if line.startswith("learn=")], (
        "a learn= rule left behind records instead of denying"
    )


COMPLETE_MODE_SCRIPT = f"""
from agno_demo.tools import evaluate_expression, fetch_webpage
print("SANE", evaluate_expression("2*(3+4)"))
print("ESCAPE", evaluate_expression({POPEN_ESCAPE!r}))
print("DENIED", fetch_webpage({DENIED_URL!r})[:400])
"""


def test_scenario_d_the_complete_mode_confines_the_same_calls() -> None:
    """The whole process under `python-sb`, the other mode D2 asks for.

    Nothing calls `sandboxes()` here: the rules come from the profile handed to
    the launcher, and `is_in_sandbox()` is true from the start, so `@sandbox`
    calls the inner function directly and the bridge is never used. A tool
    verified only in partial mode says nothing about this path.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pysandboxes.python_sb",
            f"--pysandboxes-config={CONFIG_COMPLETE}",
            "-c",
            COMPLETE_MODE_SCRIPT,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=SAMPLE_ROOT,
    )

    assert "SANE 14.0" in result.stdout, result.stdout + result.stderr
    assert "process-exec" in result.stdout, result.stdout + result.stderr
    assert "refused by the sandbox" in result.stdout, result.stdout + result.stderr
