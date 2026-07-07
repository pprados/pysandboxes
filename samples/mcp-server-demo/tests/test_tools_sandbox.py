# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""What pysandboxes actually enforces on the two demonstration tools.

Both tools are declared to the MCP server through a wrapper that delegates to a
module-level ``_``-prefixed function carrying ``@sandbox``; the tests call that
inner function, which is what the server ends up invoking.

Scenario A, the negative control, runs in a **separate process**: a baseline
profile leaves ``is_in_sandbox()`` true behind it, so an armed block running
afterwards in the same process short-circuits and silently reproduces the
baseline. Checking both profiles in one process is how a blocking test becomes
incapable of failing.

Scenarios B and C run armed, against the real network. No mock: a mocked
transport proves the mock, not the rule.
"""

import subprocess
import sys
from pathlib import Path

import pytest
from pysandboxes import sandbox_denials, sandboxes

from mcp_server.main import _evaluate_expression, _fetch_webpage

SAMPLE_ROOT = Path(__file__).parent.parent
# One profile per mode, each learned in its own by `learn.py`. They are not
# interchangeable: the partial profile has to allow the bridge that runs inside
# the sandbox with the tool, and the complete one has to allow the framework's
# own dispatch. Sharing one profile would grant each mode the other's
# privileges for nothing.
CONFIG = SAMPLE_ROOT / "mcp_server" / ".py-sandboxes"
CONFIG_COMPLETE = SAMPLE_ROOT / "mcp_server" / ".py-sandboxes-complete"

# Host listed in net=ALLOW of the profile above.
ALLOWED_URL = "https://www.google.com/"
# Real, resolvable host deliberately absent from net=ALLOW. A real name keeps
# the refusal attributable to the rule instead of to an NXDOMAIN.
DENIED_URL = "https://example.com/"


def armed_kwargs() -> dict[str, object]:
    """A fully armed sandbox: Python layer plus OS provider."""
    return {
        "sandboxes_config": CONFIG,
        "py_sandbox": "true",
        "os_sandbox": "subprocess",
    }


# Reaches Popen through the subclass tree, which an empty __builtins__ does not
# hide. The expression tool is a plain eval() on purpose: what stops this is the
# sandbox, not a parser.
POPEN_ESCAPE = "[c for c in ().__class__.__base__.__subclasses__() if c.__name__=='Popen'][0](['/bin/echo','pwned'])"


def test_scenario_a_the_escape_succeeds_without_the_sandbox() -> None:
    """Without pysandboxes the malicious expression runs. Otherwise B proves nothing."""
    # `import subprocess` first: the escape walks the subclass tree, so Popen has
    # to be loaded, and in the server it always is -- anyio imports subprocess at
    # load time and starlette/fastmcp depend on anyio. A bare interpreter would
    # fail on an empty tree and prove nothing about the sandbox.
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


@pytest.mark.asyncio
async def test_scenario_b2_an_allowed_host_is_reached() -> None:
    """The host listed in net=ALLOW answers, so the rule is a whitelist and not a wall."""
    async with sandboxes(**armed_kwargs()):
        page = await _fetch_webpage(ALLOWED_URL)

    assert page.strip(), "the allowed host returned nothing"


@pytest.mark.asyncio
async def test_scenario_b1_a_host_outside_the_rules_is_refused() -> None:
    """A host absent from net=ALLOW is refused, and the refusal is attributable.

    The assertion goes through sandbox_denials() rather than the message: httpx
    reports "All connection attempts failed", which any outage produces too.
    """
    async with sandboxes(**armed_kwargs()):
        with pytest.raises(Exception) as caught:
            await _fetch_webpage(DENIED_URL)

    denials = sandbox_denials(caught.value)
    assert denials, f"no denial reported, only {caught.value!r}"
    assert any("DENIED" in denial for denial in denials), denials


@pytest.mark.asyncio
async def test_the_expression_tool_still_computes() -> None:
    async with sandboxes(**armed_kwargs()):
        assert await _evaluate_expression("2*(3+4)") == 14


@pytest.mark.asyncio
async def test_scenario_c_the_malicious_expression_is_confined() -> None:
    """The escape of scenario A reaches Popen and is refused there.

    The refusal comes from the API guard, not from the import guard:
    python-import=subprocess cannot be removed, since anyio imports it at load
    time and starlette/fastmcp depend on anyio.
    """
    async with sandboxes(**armed_kwargs()):
        with pytest.raises(Exception) as caught:
            await _evaluate_expression(POPEN_ESCAPE)

    denials = sandbox_denials(caught.value)
    assert denials, f"no denial reported, only {caught.value!r}"
    assert any("process-exec" in denial for denial in denials), denials


@pytest.mark.parametrize("profile", [CONFIG, CONFIG_COMPLETE], ids=["partial", "complete"])
def test_the_profile_is_a_whitelist(profile: Path) -> None:
    """Guard the three ways this demonstration has silently died before."""
    rules = [line.strip() for line in profile.read_text().splitlines()]
    active = [line for line in rules if line and not line.startswith("#")]

    assert "python-import=*" not in active, "a wildcard import rule voids the whitelist"
    assert not [
        line for line in active if line.startswith("python-api=ALLOW:process-exec")
    ], "allowing process-exec would void scenario C"
    assert not [
        line for line in active if line.startswith("learn=")
    ], "a profile left in learning mode records instead of denying"
