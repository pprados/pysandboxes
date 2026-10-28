# Copyright (c) 2026, Philippe PRADOS
# License: Apache V2
import os
from pathlib import Path

import pytest  # type: ignore[import-untyped]
from hypothesis import given
from hypothesis import strategies as st

from pysandboxes import guard_files
from pysandboxes.sb_types import ConfigLine
from pysandboxes.tools import (
    exit_status,
    follow_links_executable,
    get_callable_info,
    remove_comments,
    remove_config_comments,
    resolve_env_variables,
    shell_status,
    substitute_env_vars,
)

MARKERS = ""
plain = st.text(alphabet=st.characters(blacklist_characters=MARKERS + "$", blacklist_categories=("Cs",)), max_size=20)
names = st.from_regex(r"[A-Z][A-Z0-9_]{0,6}", fullmatch=True)
envs = st.dictionaries(names, plain, max_size=4)
lines = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=30)


@given(plain, envs)
def test_a_text_without_reference_is_returned_unchanged(text: str, env: dict[str, str]) -> None:
    assert resolve_env_variables(text, env) == text


@given(
    names,
    st.text(alphabet=st.characters(blacklist_characters=MARKERS + "${}", blacklist_categories=("Cs",)), max_size=10),
    envs,
)
def test_a_reference_takes_the_value_or_the_default(name: str, default: str, env: dict[str, str]) -> None:
    expected = env.get(name, default)
    assert resolve_env_variables("${%s:-%s}" % (name, default), env) == expected


@given(names, plain)
def test_a_value_holding_a_reference_is_not_expanded_again(name: str, tail: str) -> None:
    assert resolve_env_variables("${A}", {"A": "${%s}" % name + tail}) == "${%s}" % name + tail


@pytest.mark.parametrize("value", ["0", "9", "x"])
def test_a_value_holding_the_reserved_markers_is_returned_verbatim(value: str) -> None:
    assert resolve_env_variables("${A}", {"A": value}) == value


@pytest.mark.parametrize("marker", ["", ""])
def test_a_reserved_marker_in_the_text_is_refused(marker: str) -> None:
    with pytest.raises(ValueError, match="reserved"):
        resolve_env_variables("a" + marker, {})


@pytest.mark.parametrize("text", ["${}", "${A:}", "${A:b}"])
def test_a_malformed_reference_is_refused(text: str) -> None:
    with pytest.raises(ValueError):
        resolve_env_variables(text, {})


@pytest.mark.parametrize("text", ["${", "${A", "${A:-b"])
def test_an_unterminated_reference_is_kept_as_text(text: str) -> None:
    """Pins the current behaviour: only a closed `${...}` is judged, so a missing brace passes unexpanded."""
    assert resolve_env_variables(text, {}) == text


@given(st.lists(plain, max_size=5), envs)
def test_substitute_env_vars_keeps_the_length(items: list[str], env: dict[str, str]) -> None:
    assert substitute_env_vars(items, env) == items


@given(st.lists(lines, max_size=8))
def test_remove_comments_is_idempotent_and_leaves_no_comment(config: list[str]) -> None:
    once = remove_comments(config)
    assert remove_comments(once) == once
    assert all(line and not line.startswith("#") and line == line.rstrip() for line in once)


@pytest.mark.parametrize(
    "line, expected",
    [
        ("a # note", "a"),
        ("# whole", None),
        ("a '#' b # note", "a '#' b"),
        ('a "#" b', 'a "#" b'),
        ("a '\\'#' b # note", "a '\\'#' b"),
        ("   ", None),
    ],
)
def test_remove_comments_respects_quotes(line: str, expected: str | None) -> None:
    assert remove_comments([line]) == ([] if expected is None else [expected])


@given(st.lists(lines, max_size=8))
def test_remove_config_comments_keeps_the_position_of_each_survivor(config: list[str]) -> None:
    path = Path("x.profile")
    cfg = [ConfigLine(line, path, n) for n, line in enumerate(config, start=1)]
    kept = remove_config_comments(cfg)
    assert [c.ln for c in kept] == sorted(c.ln for c in kept)
    assert all(c.path == path and c.rule[0] not in "#{" for c in kept)


def test_remove_config_comments_drops_template_lines() -> None:
    cfg = [ConfigLine("{% if x %}", Path("p"), 1), ConfigLine("net=ALLOW", Path("p"), 2)]
    assert [c.rule for c in remove_config_comments(cfg)] == ["net=ALLOW"]


def test_get_callable_info_gives_the_qualified_name_of_a_method() -> None:
    class Holder:
        def method(self) -> None: ...

    _, name = get_callable_info(Holder.method)
    assert name == Holder.method.__qualname__
    assert name != "method"


def test_follow_links_executable_follows_a_relative_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The launcher runs unguarded, where readlink returns the link as written; the guard's wrapper would hand back
    # an absolute path and make the relative branch unreachable.
    monkeypatch.setattr(os, "readlink", guard_files._os_readlink)
    (tmp_path / "base" / "bin").mkdir(parents=True)
    (tmp_path / "venv" / "bin").mkdir(parents=True)
    real = tmp_path / "base" / "bin" / "python"
    real.write_text("")
    link = tmp_path / "venv" / "bin" / "python"
    link.symlink_to("../../base/bin/python")
    assert os.readlink(link) == "../../base/bin/python"
    found = follow_links_executable(link, set())
    assert tmp_path / "base" in found
    assert tmp_path / "venv" in found


@given(st.integers(min_value=0, max_value=255))
def test_shell_status_keeps_a_normal_exit_code(code: int) -> None:
    assert shell_status(code) == code


@given(st.integers(min_value=1, max_value=64))
def test_shell_status_maps_a_signal_to_128_plus_signum(signum: int) -> None:
    assert shell_status(-signum) == 128 + signum


@pytest.mark.parametrize("code, expected", [(None, 0), (3, 3), ("boom", 1), (1.5, 1)])
def test_exit_status_follows_cpython(code: object, expected: int) -> None:
    assert exit_status(SystemExit(code)) == expected


def test_exit_status_reports_a_non_integer_code_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    assert exit_status(SystemExit("boom"), report=True) == 1
    assert capsys.readouterr().err == "boom\n"
    exit_status(SystemExit(2), report=True)
    assert capsys.readouterr().err == ""
