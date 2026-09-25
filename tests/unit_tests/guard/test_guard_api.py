# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Behaviour of the guard_api layer."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import pytest

import pysandboxes
from pysandboxes.e import RuleApiPermissionError, SandBoxError
from pysandboxes.guard_api import (
    _CATEGORY_HELP,
    CATEGORIES,
    SENSITIVE_API,
    ApiRule,
    LearnApiRule,
    activate_guard,
    all_qualnames,
    generate_rules,
    is_allowed,
    parse_rules,
    patch_rules,
)
from pysandboxes.lifecycle import arm, is_armed
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine


def test_exception_is_a_permission_error() -> None:
    """User code catching PermissionError keeps working."""
    err = RuleApiPermissionError("os.system", "process-exec")
    assert isinstance(err, PermissionError)
    assert isinstance(err, SandBoxError)


def test_exception_message_tells_how_to_unblock() -> None:
    err = RuleApiPermissionError("os.system", "process-exec")
    message = str(err)
    assert "os.system" in message
    assert "process-exec" in message
    assert "python-api=ALLOW:os.system" in message
    assert "python-api=ALLOW:process-exec" in message


def test_exception_is_exported() -> None:
    assert pysandboxes.RuleApiPermissionError is RuleApiPermissionError
    assert "RuleApiPermissionError" in pysandboxes.__all__


def test_no_dead_name_in_all() -> None:
    """__all__ must not advertise names that do not exist."""
    for name in pysandboxes.__all__:
        assert getattr(pysandboxes, name, None) is not None, name


def _parse(*rules: str) -> tuple[tuple[ApiRule, ...], list[ErrorMsg]]:
    errors: list[ErrorMsg] = []
    lines = [ConfigLine(r, Path("p"), i) for i, r in enumerate(rules)]
    parsed, remaining = parse_rules(lines, errors)
    assert not remaining, "python-api= lines must be consumed"
    return parsed, errors


def test_allow_a_category() -> None:
    parsed, errors = _parse("python-api=ALLOW:threads")
    assert not errors
    assert parsed[0].allow is True
    assert parsed[0].target == "threads"
    assert parsed[0].is_category is True


def test_allow_a_function() -> None:
    parsed, errors = _parse("python-api=ALLOW:os.system")
    assert not errors
    assert parsed[0].target == "os.system"
    assert parsed[0].is_category is False


def test_deny_and_several_targets_on_one_line() -> None:
    parsed, errors = _parse("python-api=DENY:threads, os.system")
    assert not errors
    assert [r.target for r in parsed] == ["threads", "os.system"]
    assert all(r.allow is False for r in parsed)


def test_rules_accumulate_across_lines() -> None:
    parsed, errors = _parse(
        "python-api=ALLOW:threads",
        "python-api=DENY:threading.settrace",
    )
    assert not errors
    assert len(parsed) == 2


def test_wildcards() -> None:
    parsed, errors = _parse("python-api=ALLOW:*", "python-api=DENY:*")
    assert not errors
    assert [r.target for r in parsed] == ["*", "*"]


def test_other_directives_are_returned_untouched() -> None:
    errors: list[ErrorMsg] = []
    lines = [ConfigLine("expose-ro=.", Path("p"), 0)]
    parsed, remaining = parse_rules(lines, errors)
    assert not parsed
    assert not errors
    assert remaining == lines


@pytest.mark.parametrize(
    "rule",
    [
        "python-api=ALLOW:threadz",
        "python-api=ALLOW:os.systemm",
        "python-api=ALLOW:os.no_such_function",
        "python-api=threads",
        "python-api=PERMIT:threads",
        "python-api=ALLOW:threads,DENY:os.system",
        "python-api=ALLOW:",
        "python-api=ALLOW:threads,",
        "python-api=",
    ],
)
def test_rejected_syntax(rule: str) -> None:
    parsed, errors = _parse(rule)
    assert errors, f"{rule!r} should be rejected"
    assert not parsed


def test_error_carries_provenance() -> None:
    _, errors = _parse("python-api=ALLOW:threadz")
    message, path, line = errors[0]
    assert path == Path("p")
    assert line == 0
    assert "threadz" in message


def _activate(*rules: str) -> None:
    parsed, errors = _parse(*rules)
    assert not errors
    activate_guard(parsed)


@pytest.mark.parametrize(
    "rules,settrace,start",
    [
        ((), False, False),
        (("python-api=ALLOW:threads",), True, True),
        (
            (
                "python-api=ALLOW:threads",
                "python-api=DENY:threading.settrace",
            ),
            False,
            True,
        ),
        (
            (
                "python-api=DENY:threads",
                "python-api=ALLOW:threading.settrace",
            ),
            True,
            False,
        ),
        (
            (
                "python-api=DENY:threading.settrace",
                "python-api=ALLOW:threads",
            ),
            False,
            True,
        ),
    ],
)
def test_specificity_decides_not_order(rules: tuple[str, ...], settrace: bool, start: bool) -> None:
    """A function rule beats its category, whatever the line order."""
    if rules:
        _activate(*rules)
    else:
        activate_guard(())
    assert is_allowed("threading.settrace") is settrace
    assert is_allowed("threading.Thread.start") is start


def test_deny_wins_at_equal_specificity() -> None:
    _activate(
        "python-api=ALLOW:os.system",
        "python-api=DENY:os.system",
    )
    assert is_allowed("os.system") is False


def test_wildcard_allows_everything() -> None:
    _activate("python-api=ALLOW:*")
    assert all(is_allowed(q) for q in all_qualnames())


def test_wildcard_allow_with_function_deny() -> None:
    """A function-level DENY wins over ALLOW:*, nothing else is affected."""
    _activate("python-api=ALLOW:*", "python-api=DENY:os.system")
    assert is_allowed("os.system") is False
    assert all(is_allowed(q) for q in all_qualnames() if q != "os.system")


def test_wildcard_allow_and_deny_together_denies() -> None:
    """ALLOW:* and DENY:* both at wildcard level: the all() fold denies."""
    _activate("python-api=ALLOW:*", "python-api=DENY:*")
    assert not any(is_allowed(q) for q in all_qualnames())


def test_unknown_name_is_not_allowed() -> None:
    """A name outside the registry is never reported as allowed."""
    _activate("python-api=ALLOW:*")
    assert is_allowed("os.getcwd") is False


def _guarded(qualname: str) -> Callable[..., Any]:
    """Build the wrapper the patch table would install."""
    table = patch_rules(learn=False)
    return table[qualname](lambda *a, **k: "called")


def _reset_guard() -> None:
    """Undo activate_guard()/arm() so state never survives a test.

    The autouse fixture in conftest.py only resets *before* each test,
    so a test that calls arm() must reset it itself, or _armed would
    stay True to the end of the session.
    """
    from pysandboxes.lifecycle import _reset_for_tests

    _reset_for_tests()


def test_disarmed_lets_everything_through() -> None:
    activate_guard(())
    assert is_armed() is False
    assert _guarded("os.system")("ls") == "called"


def test_armed_and_denied_raises() -> None:
    activate_guard(())
    wrapped = _guarded("os.system")
    try:
        arm()
        with pytest.raises(RuleApiPermissionError) as exc:
            wrapped("ls")
        assert exc.value.qualname == "os.system"
        assert exc.value.category == "process-exec"
    finally:
        _reset_guard()


def test_armed_denies_importlib_reload() -> None:
    """reload() puts a module's original attributes back over the patches."""
    activate_guard(())
    wrapped = _guarded("importlib.reload")
    try:
        arm()
        with pytest.raises(RuleApiPermissionError) as exc:
            wrapped("os")
        assert exc.value.qualname == "importlib.reload"
        assert exc.value.category == "introspection"
    finally:
        _reset_guard()


def test_armed_and_allowed_passes() -> None:
    _activate("python-api=ALLOW:os.system")
    wrapped = _guarded("os.system")
    try:
        arm()
        assert wrapped("ls") == "called"
    finally:
        _reset_guard()


def test_arm_is_idempotent() -> None:
    activate_guard(())
    try:
        arm()
        arm()
        assert is_armed() is True
    finally:
        _reset_guard()


def test_learning_mode_records_without_raising() -> None:
    """The most critical path: learning never blocks, only records."""
    from unittest.mock import patch as mock_patch

    from pysandboxes.guard_api import LearnApiRule
    from pysandboxes.learning import set_learning_mode

    activate_guard(())  # nothing allowed
    wrapped = _guarded("os.system")
    set_learning_mode(True)
    try:
        arm()
        with mock_patch("pysandboxes.guard_api.add_learning_rule") as rec:
            assert wrapped("ls") == "called"
        rec.assert_called_once_with(LearnApiRule("os.system"))
    finally:
        set_learning_mode(False)
        _reset_guard()


def test_patch_table_covers_every_applicable_entry() -> None:
    """Every registry entry is patched except the inapplicable ones.

    guard_import._apply_patch calls getattr before the factory, so an
    entry absent from an imported module would raise at startup. A
    registry name redirected by _PATCH_TARGET is checked against its
    patch target, since that is the table's actual key.

    Two exclusion sets, for two different reasons: _not_applicable()
    drops what this interpreter has no entry for, and _OWNED_ELSEWHERE
    drops what guard_eval patches instead.
    """
    from pysandboxes.guard_api import _OWNED_ELSEWHERE, _PATCH_TARGET, _not_applicable

    table = patch_rules(learn=False)
    skip = _not_applicable() | _OWNED_ELSEWHERE
    for qualname in all_qualnames():
        target = _PATCH_TARGET.get(qualname, qualname)
        if qualname in skip:
            assert target not in table, qualname
        else:
            assert target in table, qualname


def test_learning_still_emits_the_category_guard_eval_owns() -> None:
    """_OWNED_ELSEWHERE must not be folded into _not_applicable().

    The latter is also subtracted in generate_rules, so collapsing the two
    would silently stop learning mode from ever proposing a dynamic-code
    line -- an application that calls eval would be handed a rule file that
    does not mention it.
    """
    from pysandboxes.guard_api import _OWNED_ELSEWHERE, _not_applicable

    assert not _not_applicable() & _OWNED_ELSEWHERE
    lines = generate_rules({LearnApiRule("builtins.eval")})
    assert any("dynamic-code" in line for line in lines)


def test_class_entries_keep_their_class_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patching a class-backed entry must not turn it into a function.

    _PATCH_TARGET redirects these entries to their __init__, which
    mutates the class in place instead of replacing it: isinstance,
    issubclass and subclassing must keep working, armed or not.
    """
    import subprocess

    table = patch_rules(learn=False)
    original_init = subprocess.Popen.__init__
    wrapped = table["subprocess.Popen.__init__"](original_init)
    monkeypatch.setattr(subprocess.Popen, "__init__", wrapped)

    instance = object.__new__(subprocess.Popen)
    assert isinstance(instance, subprocess.Popen)
    assert issubclass(subprocess.Popen, subprocess.Popen)

    class SubPopen(subprocess.Popen):
        pass

    assert issubclass(SubPopen, subprocess.Popen)


def test_class_entry_denies_and_allows_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The redirected wrapper still enforces, on the real target."""
    import subprocess
    import sys

    table = patch_rules(learn=False)
    original_init = subprocess.Popen.__init__
    wrapped = table["subprocess.Popen.__init__"](original_init)
    monkeypatch.setattr(subprocess.Popen, "__init__", wrapped)
    cmd = [sys.executable, "-c", "pass"]

    activate_guard(())
    try:
        arm()
        with pytest.raises(RuleApiPermissionError) as exc:
            subprocess.Popen(cmd)
        assert exc.value.qualname == "subprocess.Popen"
    finally:
        _reset_guard()

    _activate("python-api=ALLOW:subprocess.Popen")
    try:
        arm()
        proc = subprocess.Popen(cmd)
        proc.wait()
    finally:
        _reset_guard()


def test_every_patched_entry_actually_resolves() -> None:
    """A patched name must exist, or startup would raise."""
    import importlib

    from pysandboxes.guard_api import split_qualname

    for qualname in patch_rules(learn=False):
        module_name, attribute_path = split_qualname(qualname)
        try:
            obj: Any = importlib.import_module(module_name)
        except ImportError:
            continue
        for node in attribute_path.split("."):
            obj = getattr(obj, node)
        assert obj is not None


def test_factory_does_not_wrap_twice() -> None:
    """An object already guarded through an alias is not re-wrapped."""
    table = patch_rules(learn=False)
    once = table["os.system"](lambda *a, **k: "called")
    twice = table[f"{os.name if os.name == 'nt' else 'posix'}.system"](once)
    assert twice is once


def test_partial_category_yields_function_lines() -> None:
    activate_guard(())
    lines = generate_rules({LearnApiRule("os.system")})
    assert "python-api=ALLOW:os.system" in lines
    assert "python-api=ALLOW:process-exec" not in lines


def test_full_category_yields_one_category_line() -> None:
    activate_guard(())
    learned = {LearnApiRule(q) for q in SENSITIVE_API["introspection"]}
    lines = generate_rules(learned)
    assert "python-api=ALLOW:introspection" in lines
    for qualname in SENSITIVE_API["introspection"]:
        assert f"python-api=ALLOW:{qualname}" not in lines


def test_optional_entries_do_not_block_category_line() -> None:
    """A category holding OPTIONAL entries must still emit its line.

    ``threads`` holds three OPTIONAL entries (version-dependent thread
    launch primitives), never patched on this interpreter and so never
    observed. Comparing against the whole category would make it
    permanently incomplete; only the applicable entries must count.
    """
    from pysandboxes.guard_api import _not_applicable

    activate_guard(())
    skip = _not_applicable()
    applicable = [q for q in SENSITIVE_API["threads"] if q not in skip]
    learned = {LearnApiRule(q) for q in applicable}
    lines = generate_rules(learned)
    assert "python-api=ALLOW:threads" in lines


def test_learning_emits_a_parseable_line_for_deserialization() -> None:
    """A recorded `pickle.loads` call must generate a line that parses back.

    `deserialization` is in _WARN_CATEGORIES, so it matters which shape comes
    out: one observed function must stay a function line, not collapse into a
    category line that would silently grant the other three.
    """
    activate_guard(())
    lines = generate_rules({LearnApiRule("pickle.loads")})
    directives = [ln for ln in lines if not ln.startswith("#")]
    assert "python-api=ALLOW:pickle.loads" in directives
    assert "python-api=ALLOW:deserialization" not in directives
    _, errors = _parse(*directives)
    assert not errors, errors


def test_the_whole_deserialization_category_collapses_to_one_line() -> None:
    """All four observed: the category line replaces the function lines."""
    activate_guard(())
    learned = {LearnApiRule(q) for q in SENSITIVE_API["deserialization"]}
    lines = generate_rules(learned)
    assert "python-api=ALLOW:deserialization" in lines
    for qualname in SENSITIVE_API["deserialization"]:
        assert f"python-api=ALLOW:{qualname}" not in lines


def test_category_completed_by_already_allowed_functions() -> None:
    """The union of allowed and learned decides, not the learned set."""
    already = SENSITIVE_API["introspection"][:-1]
    _activate(*(f"python-api=ALLOW:{q}" for q in already))
    last = SENSITIVE_API["introspection"][-1]
    lines = generate_rules({LearnApiRule(last)})
    assert "python-api=ALLOW:introspection" in lines
    assert f"python-api=ALLOW:{last}" not in lines


def test_other_learning_rules_are_ignored() -> None:
    activate_guard(())
    assert generate_rules({"not-an-api-rule"}) == []


def test_generated_lines_parse_back_without_error() -> None:
    activate_guard(())
    exec_rule = LearnApiRule("os.system")
    trace_rule = LearnApiRule("sys.settrace")
    lines = generate_rules({exec_rule, trace_rule})
    directives = [ln for ln in lines if not ln.startswith("#")]
    _, errors = _parse(*directives)
    assert not errors, errors


def test_category_help_covers_every_category() -> None:
    """A missing entry would raise at learning time, not at import time."""
    assert set(_CATEGORY_HELP) == CATEGORIES


def test_armed_denies_pickle_loads() -> None:
    """A pickle stream names a callable and calls it: no source to parse."""
    activate_guard(())
    wrapped = _guarded("pickle.loads")
    try:
        arm()
        with pytest.raises(RuleApiPermissionError) as exc:
            wrapped(b"")
        assert exc.value.qualname == "pickle.loads"
        assert exc.value.category == "deserialization"
    finally:
        _reset_guard()


def test_armed_denies_the_pickle_c_twin() -> None:
    """`pickle.loads is _pickle.loads`, so a table naming only one is walked
    around with a single `import _pickle`."""
    activate_guard(())
    wrapped = _guarded("_pickle.loads")
    try:
        arm()
        with pytest.raises(RuleApiPermissionError) as exc:
            wrapped(b"")
        assert exc.value.qualname == "_pickle.loads"
    finally:
        _reset_guard()


def test_the_file_variant_is_registered_too() -> None:
    """`pickle.load(fp)` runs the same opcodes as `loads`."""
    for qualname in ("pickle.load", "_pickle.load"):
        assert qualname in SENSITIVE_API["deserialization"]


@pytest.mark.xfail(
    strict=True,
    reason="Unpickler is an immutable C type: neither __init__ nor load can be "
    "patched, and rebinding the module name to a function would break the "
    "subclassing a restricted unpickler needs",
)
def test_the_unpickler_route_is_guarded() -> None:
    """`Unpickler(fp).load()` reaches the opcodes without touching `loads`.

    The payload is deliberately harmless: what this pins is that the guard
    does not fire on the route, not what a hostile stream would do with it.
    """
    import io
    import pickle as pickle_module

    activate_guard(())
    try:
        arm()
        benign = pickle_module.dumps({"harmless": 1})
        with pytest.raises(RuleApiPermissionError):
            pickle_module.Unpickler(io.BytesIO(benign)).load()
    finally:
        _reset_guard()


@pytest.mark.skipif(sys.platform == "win32", reason="probe script assumes posix")
def test_pickle_loads_and_its_twin_are_refused_end_to_end(tmp_path: Path) -> None:
    """The point of the registration, under a real `python-sb` start.

    Run out of process: the patches are posted by the import hook, so a table
    inspection would prove nothing about what an interpreter actually does.
    """
    work = tmp_path / "work"
    work.mkdir()
    repo = Path(__file__).resolve().parents[3]
    (work / ".py-sandboxes").write_text(
        "py-sandbox=true\nos-sandbox=subprocess\npython-import=*\n" f"expose-rw={work}\nexpose-ro={repo}\n"
    )
    (work / "probe.py").write_text(
        "import pickle\n"
        "import _pickle\n"
        "from pysandboxes.e import SandBoxError\n"
        "blob = pickle.dumps({'harmless': 1})\n"
        'for tag, call in (("pickle.loads", lambda: pickle.loads(blob)),\n'
        '                  ("_pickle.loads", lambda: _pickle.loads(blob))):\n'
        "    try:\n"
        "        call()\n"
        "        print(tag, 'ALLOWED')\n"
        "    except SandBoxError:\n"
        "        print(tag, 'GUARD')\n"
        "    except BaseException as exc:\n"
        "        print(tag, 'OTHER', type(exc).__name__)\n"
    )

    result = subprocess.run(
        [sys.executable, "-m", "pysandboxes.python_sb", "probe.py"],
        capture_output=True,
        text=True,
        cwd=work,
        env={**os.environ, "TMPDIR": str(work)},
    )

    assert "pickle.loads GUARD" in result.stdout, result.stdout + result.stderr
    assert "_pickle.loads GUARD" in result.stdout, result.stdout + result.stderr
