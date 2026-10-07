# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2
"""Behaviour of the guard_import layer.

Only the pure parts are covered here. ``GuardFinder`` and ``GuardLoader`` mutate
``sys.meta_path`` and ``sys.modules``, so they belong to the integration tests.
"""

from pathlib import Path
from types import ModuleType
from typing import Any, Callable, cast

import pytest

from pysandboxes import guard_import
from pysandboxes.e import RuleModuleNotFoundError
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


def test_in_the_user_code_a_relative_import_is_left_to_the_finder(monkeypatch: pytest.MonkeyPatch) -> None:
    _activate(monkeypatch, ())
    import_, import_module = _guarded_imports()
    with user_code():
        assert import_("decoder", {"__package__": "json"}, None, (), 1) == "decoder"
        assert import_("decoder", level=1) == "decoder"
        assert import_module(".decoder", "json") == ".decoder"


def test_in_the_user_code_learning_records_the_import(monkeypatch: pytest.MonkeyPatch) -> None:
    _activate(monkeypatch, ())
    recorded: list[Any] = []
    monkeypatch.setattr(guard_import, "is_learning_mode", lambda: True)
    monkeypatch.setattr(guard_import, "add_learning_rule", recorded.append)
    import_, _ = _guarded_imports()
    with user_code():
        assert import_("json") == "json"
    assert recorded == [LearnImportRule("json")]


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


def test_in_the_user_code_a_module_never_evicted_is_not_judged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The finder never sees sys, builtins or warnings: the complete mode asks no rule for them either."""
    _activate(monkeypatch, ())
    import_, import_module = _guarded_imports()
    with user_code():
        assert import_("sys") == "sys"
        assert import_module("warnings") == "warnings"


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
