# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Behaviour of the guard_import layer.

Only the pure parts are covered here. ``GuardFinder`` and ``GuardLoader`` mutate
``sys.meta_path`` and ``sys.modules``, so they belong to the integration tests.
"""

import logging
import sys
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

import pytest

from pysandboxes import guard_import
from pysandboxes.e import RuleModuleNotFoundError
from pysandboxes.guard_files import LearnFileRule
from pysandboxes.guard_import import (
    LearnImportRule,
    PatchRule,
    _conv_patch_rules,
    _group_by_width,
    _is_import_allowed,
    generate_rules,
    parse_rules,
    patch_rules,
    user_code,
)
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine, ConfigLines


def _parse(*rules: str) -> tuple[tuple[str, ...], ConfigLines]:
    errors: list[ErrorMsg] = []
    lines: ConfigLines = [ConfigLine(rule, Path(), i) for i, rule in enumerate(rules)]
    parsed, remaining = parse_rules(lines, errors)
    assert not errors, "python-import= lines never fail to parse"
    return parsed, remaining


def test_a_single_module() -> None:
    parsed, remaining = _parse("python-import=os")
    assert parsed == ("os",)
    assert remaining == []


@pytest.mark.xfail(
    strict=True,
    reason="cached sys.modules entries bypass import mediation; documented in wiki/audit-python-security.md",
)
def test_cached_module_is_not_available_through_sys_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the known import-policy bypass without treating it as an OS-boundary escape."""
    import json

    _activate(monkeypatch, ())
    assert sys.modules["json"] is json
    with user_code():
        with pytest.raises(RuleModuleNotFoundError):
            _ = sys.modules["json"]


def test_several_modules_on_one_line_are_split_and_stripped() -> None:
    parsed, _ = _parse("python-import=os, sys ,json")
    assert parsed == ("os", "sys", "json")


def test_rules_accumulate_across_lines() -> None:
    parsed, _ = _parse("python-import=os", "python-import=sys")
    assert parsed == ("os", "sys")


def test_a_wildcard_collapses_every_other_module() -> None:
    """``*`` opens everything, so keeping the other names would be misleading."""
    parsed, _ = _parse("python-import=os", "python-import=*", "python-import=sys")
    assert parsed == ("*",)


def test_other_directives_are_returned_untouched() -> None:
    parsed, remaining = _parse("python-import=os", "env=FOO=bar")
    assert parsed == ("os",)
    assert [line.rule for line in remaining] == ["env=FOO=bar"]


def _activate(monkeypatch: pytest.MonkeyPatch, rules: tuple[str, ...]) -> None:
    monkeypatch.setattr(guard_import, "_rules", rules)
    # The set is process-wide: an earlier test's imports must not leak into the verdict.
    monkeypatch.setattr(guard_import, "_framework_names", set())


def test_no_rule_denies_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty rule set is a deny-all, not a missing filter."""
    _activate(monkeypatch, ())
    assert not _is_import_allowed("os")


def test_the_package_itself_is_always_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _activate(monkeypatch, ())
    assert _is_import_allowed("pysandboxes")


def test_the_package_name_is_matched_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    _activate(monkeypatch, ())
    assert not _is_import_allowed("pysandboxesx")


def test_a_listed_module_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _activate(monkeypatch, ("os",))
    assert _is_import_allowed("os")
    assert not _is_import_allowed("sys")


def test_a_wildcard_allows_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    _activate(monkeypatch, _parse("python-import=*")[0])
    assert _is_import_allowed("anything")


def test_an_empty_first_rule_does_not_open_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python-import=`` (an empty value) must not act as a wildcard: only ``"*"`` does."""
    _activate(monkeypatch, _parse("python-import=")[0])
    assert not _is_import_allowed("os")


def test_a_bare_key_patches_the_whole_module() -> None:
    rules = _conv_patch_rules({"os": str})
    assert rules["os"] == (guard_import.PatchRule("", str),)


def test_a_dotted_key_keeps_the_attribute_path() -> None:
    rules = _conv_patch_rules({"os.path.exists": str})
    assert rules["os"] == (guard_import.PatchRule("path.exists", str),)


def test_entries_are_grouped_by_top_level_module() -> None:
    rules = _conv_patch_rules({"os.system": str, "os.getcwd": repr, "sys.exit": str})
    os_patches = cast(tuple[guard_import.PatchRule, ...], rules["os"])
    assert {patch.code_path for patch in os_patches} == {"system", "getcwd"}
    assert len(rules["sys"]) == 1


def test_no_group_without_item() -> None:
    assert _group_by_width([], 10) == []


def test_items_are_joined_until_the_width_is_reached() -> None:
    assert _group_by_width(["aa", "bb", "cc"], 10) == ["aa, bb, cc"]


def test_a_too_long_group_is_split() -> None:
    assert _group_by_width(["aaaa", "bbbb", "cccc"], 10) == ["aaaa, bbbb", "cccc"]


def test_a_single_item_wider_than_the_limit_is_kept() -> None:
    assert _group_by_width(["a" * 20], 10) == ["a" * 20]


def test_the_import_functions_are_patched() -> None:
    assert set(patch_rules(learn=False)) == {"builtins.__import__", "importlib.__import__", "importlib.import_module"}


def _imported(name: str, *args: Any, **kwargs: Any) -> str:
    return name


def _guarded_imports() -> tuple[Callable[..., Any], Callable[..., Any]]:
    """The wrappers around a stand-in for the import: the guard of this process already holds the real one."""
    return guard_import._wrap_import(_imported), guard_import._wrap_import_module(_imported)


def test_outside_the_user_code_an_import_is_not_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    _activate(monkeypatch, ())
    import_, import_module = _guarded_imports()
    assert import_("json") == "json"
    assert import_module("json") == "json"


def test_in_the_user_code_a_module_the_daemon_loaded_is_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    _activate(monkeypatch, ())
    monkeypatch.setattr(guard_import, "_framework_names", {"json"})
    import_, import_module = _guarded_imports()
    with user_code():
        with pytest.raises(RuleModuleNotFoundError, match="'json'"):
            import_("json.decoder", {"__name__": "uvicorn"}, None, (), 0)
        with pytest.raises(RuleModuleNotFoundError, match="'json'"):
            import_module("json")


def test_in_the_user_code_a_rule_grants_the_import(monkeypatch: pytest.MonkeyPatch) -> None:
    _activate(monkeypatch, ("json",))
    import_, import_module = _guarded_imports()
    with user_code():
        assert import_("json.decoder") == "json.decoder"
        assert import_module("json") == "json"


def test_in_the_user_code_a_relative_import_is_judged_on_its_absolute_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """A loaded module never meets the finder: a relative import of it is judged like an absolute one."""
    _activate(monkeypatch, ("json",))
    import_, import_module = _guarded_imports()
    with user_code():
        assert import_("decoder", {"__package__": "json"}, None, (), 1) == "decoder"
        assert import_module(".decoder", "json") == ".decoder"
        with pytest.raises(RuleModuleNotFoundError, match="'email'"):
            import_("parser", {"__package__": "email"}, None, (), 1)
        with pytest.raises(RuleModuleNotFoundError, match="'email'"):
            import_module(".parser", "email")


def test_in_the_user_code_learning_records_the_import(monkeypatch: pytest.MonkeyPatch) -> None:
    _activate(monkeypatch, ())
    recorded: list[Any] = []
    monkeypatch.setattr(guard_import, "is_learning_mode", lambda: True)
    monkeypatch.setattr(guard_import, "add_learning_rule", recorded.append)
    import_, _ = _guarded_imports()
    with user_code():
        assert import_("json") == "json"
    assert recorded == [LearnImportRule("json")]


def test_importlib_learning_records_the_module_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _activate(monkeypatch, ())
    recorded: list[Any] = []
    spec = ModuleSpec("demo.main", loader=None, origin=str(tmp_path / "demo" / "main.py"))

    class Finder:
        def find_spec(self, fullname: str, path: Any, target: Any = None) -> ModuleSpec | None:
            return spec if fullname == "demo.main" else None

    monkeypatch.setattr(guard_import, "_in_framework_window", lambda: False)
    monkeypatch.setattr(guard_import, "is_in_sandbox", lambda: True)
    monkeypatch.setattr(guard_import, "is_learning_mode", lambda: True)
    monkeypatch.setattr(guard_import, "add_learning_rule", recorded.append)
    guard_finder = guard_import.GuardFinder()
    monkeypatch.setattr(sys, "meta_path", [guard_finder, Finder()])

    found = guard_finder.find_spec("demo.main", [str(tmp_path / "demo")])

    assert found is spec
    assert LearnImportRule("demo") in recorded
    assert spec.origin is not None
    assert LearnFileRule(Path(spec.origin), False) in recorded


def test_importlib_learning_does_not_expose_the_framework_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _activate(monkeypatch, ())
    recorded: list[Any] = []
    spec = ModuleSpec("pysandboxes.guard_import", loader=None, origin=str(tmp_path / "pysandboxes" / "guard_import.py"))

    class Finder:
        def find_spec(self, fullname: str, path: Any, target: Any = None) -> ModuleSpec | None:
            return spec if fullname == "pysandboxes.guard_import" else None

    guard_finder = guard_import.GuardFinder()
    monkeypatch.setattr(sys, "meta_path", [guard_finder, Finder()])
    monkeypatch.setattr(guard_import, "_in_framework_window", lambda: False)
    monkeypatch.setattr(guard_import, "is_in_sandbox", lambda: True)
    monkeypatch.setattr(guard_import, "is_learning_mode", lambda: True)
    monkeypatch.setattr(guard_import, "add_learning_rule", recorded.append)

    assert guard_finder.find_spec("pysandboxes.guard_import", [str(tmp_path / "pysandboxes")]) is not None

    assert not any(isinstance(rule, LearnFileRule) for rule in recorded)


def test_in_the_user_code_a_missing_module_is_not_learned(monkeypatch: pytest.MonkeyPatch) -> None:
    """An optional dependency probed with ``try: import x`` stays out of the profile, as the finder does."""
    _activate(monkeypatch, ())
    recorded: list[Any] = []
    monkeypatch.setattr(guard_import, "is_learning_mode", lambda: True)
    monkeypatch.setattr(guard_import, "add_learning_rule", recorded.append)

    def missing(name: str, *args: Any, **kwargs: Any) -> Any:
        raise ModuleNotFoundError(name)

    with user_code():
        with pytest.raises(ModuleNotFoundError):
            guard_import._wrap_import(missing)("brotli")
        with pytest.raises(ModuleNotFoundError):
            guard_import._wrap_import_module(missing)("brotli")
    assert recorded == []


def test_direct_call_with_exactly_three_extra_positional_args(monkeypatch: pytest.MonkeyPatch) -> None:
    """``__import__(name, globals, locals, fromlist)``, with no ``level``, must default it to 0."""
    _activate(monkeypatch, ())
    import_, _ = _guarded_imports()
    assert import_("json", {}, {}, ()) == "json"


def test_a_forged_copy_of_a_kept_librarys_globals_is_not_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_caller_module`` must compare the caller's globals by identity, not equality.

    A relative import made by the real ``asyncio`` package's own code is exempt from the user's
    rules; a merely ``==``-equal copy of its ``__dict__`` (e.g. ``exec(code, dict(asyncio.__dict__))``)
    must not inherit that exemption.
    """
    _activate(monkeypatch, ())
    wrapped = guard_import._wrap_import(_imported)
    real_dict = sys.modules["asyncio"].__dict__
    code = compile("def call(fn, *a, **k):\n    return fn(*a, **k)\n", "<forged>", "exec")
    import_args = ({"__name__": "asyncio", "__path__": ["<asyncio>"]}, None, (), 1)

    exec(code, real_dict)
    call_from_real = real_dict.pop("call")
    copy_dict = dict(real_dict)  # == real_dict in content, but a different object
    exec(code, copy_dict)
    call_from_copy = copy_dict.pop("call")

    with user_code():
        # The real asyncio module's own relative import is exempt: no rule is asked for it.
        assert call_from_real(wrapped, "subprocess", *import_args) == "subprocess"
        # A forged, equal-but-not-identical copy of the same dict must be judged like anyone else.
        with pytest.raises(RuleModuleNotFoundError, match="asyncio"):
            call_from_copy(wrapped, "subprocess", *import_args)


def test_in_the_user_code_a_module_never_evicted_is_not_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The finder never sees sys, builtins or warnings: the complete mode asks no rule for them either."""
    _activate(monkeypatch, ())
    import_, import_module = _guarded_imports()
    with user_code():
        assert import_("sys") == "sys"
        assert import_module("warnings") == "warnings"


def test_find_distributions_with_no_context_returns_nothing() -> None:
    """``context=None`` must build a fresh ``Context()``, not stay ``None``."""
    assert list(guard_import.GuardFinder.find_distributions()) == []


def test_find_distributions_without_a_name_finds_nothing() -> None:
    """Both ``name`` and ``path`` must be set: a path alone must not list every distribution."""
    import importlib.metadata

    context = importlib.metadata.DistributionFinder.Context(path=sys.path)
    assert context.name is None
    assert list(guard_import.GuardFinder.find_distributions(context)) == []


def test_an_unsafe_name_does_not_stop_later_names_from_being_generated() -> None:
    """The per-item ``continue`` must only skip the unsafe name, not abort the whole scan
    (``break``): a ``set`` would leave that to the (randomised) hash order, so the unsafe
    name is placed first in an ordered list instead."""
    evil_name = "evil\nname"
    learn = cast("set[Any]", [LearnImportRule(evil_name), LearnImportRule("json")])
    lines = generate_rules(learn)
    assert any(line.startswith("python-import=json") for line in lines)


def test_an_uppercase_module_name_is_not_miscategorized_as_standard() -> None:
    """``name[0] == "_"`` must not become a lexicographic comparison: ``"PIL"`` sorts before ``"_"``."""
    lines = generate_rules({LearnImportRule("PIL")})
    text = "\n".join(lines)
    assert "External modules" in text
    assert "Standard Python" not in text


def test_learned_modules_are_sorted_by_danger() -> None:
    """The generated file must warn about the modules that break the sandbox."""
    lines = generate_rules({LearnImportRule("subprocess"), LearnImportRule("json"), LearnImportRule("mycompany")})
    text = "\n".join(lines)

    assert "Dangerous" in text
    assert "python-import=subprocess" in text
    assert "Standard Python" in text
    assert "python-import=json" in text
    assert "External modules" in text
    assert "python-import=mycompany" in text


def test_a_deprecated_module_gets_its_own_section() -> None:
    lines = generate_rules({LearnImportRule("cgi")})
    text = "\n".join(lines)

    assert "Deprecated" in text
    assert "python-import=cgi" in text


def test_other_learning_rules_are_ignored() -> None:
    assert generate_rules({"not-an-import-rule"}) == []


def test_generated_lines_parse_back_without_error() -> None:
    lines = generate_rules({LearnImportRule("json"), LearnImportRule("mycompany")})
    directives = [line for line in lines if line.startswith("python-import=")]
    parsed, _ = _parse(*directives)

    assert "json" in parsed
    assert "mycompany" in parsed


def test_a_module_name_with_a_newline_is_skipped_not_injected(caplog: pytest.LogCaptureFixture) -> None:
    """NA2: ``importlib.import_module()`` accepts a name that is not a valid Python
    identifier, and a real package directory can be named that way on disk
    (``evilpkg\\nos-sandbox=none\\n#``). Writing it unescaped into
    ``python-import=<name>`` would reload as three lines -- a real
    ``python-import=evilpkg`` rule, then a free-standing ``os-sandbox=none``, then
    a comment -- instead of the single rule that was observed."""
    evil_name = "evilpkg\nos-sandbox=none\n#"
    with caplog.at_level(logging.WARNING, logger="pysandboxes.guard_import"):
        lines = generate_rules({LearnImportRule(evil_name), LearnImportRule("json")})

    assert all("\n" not in line for line in lines)
    assert not any(evil_name in line or "evilpkg" in line for line in lines)
    assert any(line.startswith("python-import=json") for line in lines)
    assert any("unsafe module name" in r.getMessage() for r in caplog.records)


def test_a_module_name_with_a_hash_is_skipped() -> None:
    """A name with no newline still corrupts the line: ``#`` is an unquoted
    end-of-line comment marker, so ``python-import=evil#pkg`` would reload as
    ``python-import=evil``, a different, wider rule than what was observed."""
    lines = generate_rules({LearnImportRule("evil#pkg")})
    assert lines == []


def test_packaged_resources_stay_readable_while_the_guard_is_armed() -> None:
    """``importlib.resources.files()`` must reach the real reader through GuardLoader.

    The autouse fixture arms the import guard, so ``pysandboxes.__spec__.loader`` is a
    GuardLoader here. A loader that does not forward ``get_resource_reader`` makes
    ``files()`` fall back to a degraded wrapper whose paths have no ``resolve()``, which
    broke the bwrap and firejail daemons: both load their template that way.
    """
    import importlib.resources
    import sys

    from pysandboxes.guard_import import GuardLoader

    spec = sys.modules["pysandboxes"].__spec__
    assert spec is not None
    assert isinstance(spec.loader, GuardLoader), "guard not armed"

    template = importlib.resources.files("pysandboxes") / "templates" / "bwrap.template"
    # `resolve()` is the point of the test: a degraded Traversable wrapper does not
    # have it, which is exactly the regression guarded here.
    assert Path(str(template)).resolve().is_file()


def test_a_function_missing_on_this_platform_is_left_unpatched(monkeypatch: pytest.MonkeyPatch) -> None:
    # `os.listxattr` exists on Linux only: macOS and Windows failed on it before
    # any test could run.
    module = ModuleType("fake")
    module.present = lambda: "original"  # type: ignore[attr-defined]
    monkeypatch.setattr(
        guard_import,
        "_patch_rules",
        {
            "fake": (
                PatchRule("absent", lambda original: original),
                PatchRule("present", lambda original: lambda: "patched"),
            )
        },
    )

    guard_import._apply_patch(module, "fake")

    assert module.present() == "patched"  # type: ignore[attr-defined]
    assert not hasattr(module, "absent")


def test_a_guard_loader_never_wraps_another_guard_loader() -> None:
    """Re-wrapping the previous activation's loader grew one level per activation, until the stack overflowed."""
    import importlib.machinery
    import sys

    real_loader = importlib.machinery.SourceFileLoader("fake", "/nonexistent/fake.py")
    spec = importlib.machinery.ModuleSpec("fake", real_loader)
    for _ in range(sys.getrecursionlimit() + 10):
        spec = importlib.machinery.ModuleSpec("fake", guard_import.GuardLoader("fake", spec))

    loader = cast(guard_import.GuardLoader, spec.loader)
    assert loader.original_loader is real_loader
    assert loader.get_resource_reader("fake") is not None  # Delegates in one step, no RecursionError


def test_a_guard_loader_answers_the_source_questions_of_the_loader_it_wraps(tmp_path: Path) -> None:
    """``runpy`` asks for the code of a module already imported through the guard: ``python -m <module>``."""
    import importlib.machinery

    source = tmp_path / "wrapped.py"
    source.write_text("VALUE = 1\n", newline="\n")
    real_loader = importlib.machinery.SourceFileLoader("wrapped", str(source))
    loader = guard_import.GuardLoader("wrapped", importlib.machinery.ModuleSpec("wrapped", real_loader))

    assert loader.get_filename("wrapped") == str(source)  # type: ignore[attr-defined]
    assert loader.get_source("wrapped") == "VALUE = 1\n"  # type: ignore[attr-defined]
    assert loader.is_package("wrapped") is False  # type: ignore[attr-defined]
    assert loader.get_data(str(source)) == b"VALUE = 1\n"  # type: ignore[attr-defined]
    namespace: dict[str, Any] = {}
    exec(loader.get_code("wrapped"), namespace)  # type: ignore[attr-defined]
    assert namespace["VALUE"] == 1


@pytest.mark.parametrize("original", [None, object()], ids=["no loader", "a loader without the methods"])
def test_a_guard_loader_does_not_pretend_the_wrapped_loader_answers(original: Any) -> None:
    import importlib.machinery

    spec = importlib.machinery.ModuleSpec("wrapped", original)
    loader = guard_import.GuardLoader("wrapped", spec)

    assert not hasattr(loader, "get_code")


def test_a_guard_loader_has_no_other_made_up_attribute() -> None:
    loader = guard_import.GuardLoader("wrapped", None)

    with pytest.raises(AttributeError, match="no_such_thing"):
        loader.no_such_thing  # type: ignore[attr-defined]  # noqa: B018


def _activation_probe(before: str) -> str:
    """Run an activation with an allow-list that omits ntpath, after ``before``; report what is loaded."""
    import subprocess

    code = (
        "import sys\n"
        "from pysandboxes import guard_import\n"
        f"{before}\n"
        "guard_import.activate_guard_import({}, ('json',))\n"
        "print('ntpath' in sys.modules and sys.modules['ntpath'] is not None)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_ntpath_stays_loaded_for_the_pathlib_of_an_old_python_3_12() -> None:
    """Before 3.12.4 pathlib imports ntpath on each Path built from a Path: an evicted module would be refused."""
    assert _activation_probe("sys.modules.pop('ntpath', None)") == "True"
    assert _activation_probe("import ntpath") == "True"


def test_an_interpreter_without_ntpath_still_activates() -> None:
    assert _activation_probe("sys.modules['ntpath'] = None") == "False"


def test_a_module_is_not_judged_while_the_import_guard_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """With ``py-sandbox=false`` no rule is loaded: judging then would refuse every import, ``-m`` included."""
    monkeypatch.setattr(guard_import, "_activated", False)
    monkeypatch.setattr(guard_import, "_rules", ())

    guard_import._judge_user_import("tests")
    guard_import._judge_user_import("tests.integration_tests.tst_file_probe")
