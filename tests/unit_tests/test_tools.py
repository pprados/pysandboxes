import random
import re
import time
from pathlib import Path
from typing import List

import pytest

from pysandboxes.tools import (
    GlobPattern,
    _remove_comment,
    exit_status,
    find_config_for_module,
    follow_links_executable,
    resolve_env_variables,
)


def test_remove_comment_basic() -> None:
    """Test basic comment removal"""
    test_cases: List[tuple[str, str]] = [
        ("abc # comment", "abc"),
        ("no comment here", "no comment here"),
        ("# full comment", ""),
        ("", ""),
        ("   # indented comment", ""),
    ]

    for input_line, expected in test_cases:
        result: str = _remove_comment(input_line)
        assert result == expected


def test_remove_comment_with_quotes() -> None:
    """Test comment removal with quoted strings"""
    test_cases: List[tuple[str, str]] = [
        ('abc " def # ghi" # comment', 'abc " def # ghi"'),
        (
            "path='/home/user # not comment' # real comment",
            "path='/home/user # not comment'",
        ),
        ('mixed="single \' inside" # comment', 'mixed="single \' inside"'),
        ("escaped_quote='don\\'t remove' # comment", "escaped_quote='don\\'t remove'"),
        (
            'no_end_quote="unclosed # should not remove',
            'no_end_quote="unclosed # should not remove',
        ),
    ]

    for input_line, expected in test_cases:
        result: str = _remove_comment(input_line)
        assert result == expected


@pytest.mark.parametrize("reference", ["${A:B}", "${MY-VAR}", "${}", "x${A:B}y${C}"])
def test_resolve_env_variables_rejects_an_invalid_reference(reference: str) -> None:
    """A reference the syntax does not cover is refused instead of looping forever."""
    with pytest.raises(ValueError, match="Invalid variable reference"):
        resolve_env_variables(reference, {"A": "a", "C": "c"})


def test_resolve_env_variables_never_expands_a_value() -> None:
    """A value holding "${...}" is inserted as is: neither expanded again nor taken for a bad reference."""
    envs = {"A": "${B}", "B": "secret", "C": "${A:B}"}
    assert resolve_env_variables("x${A}y", envs) == "x${B}y"
    assert resolve_env_variables("[${C}]", envs) == "[${A:B}]"


def test_substitute_config_env_vars_reports_the_line_of_an_invalid_reference() -> None:
    from pysandboxes.e import ConfigSyntaxError
    from pysandboxes.sb_types import ConfigLine
    from pysandboxes.tools import substitute_config_env_vars

    lines = [ConfigLine("expose-ro=${HOME}", Path("p.conf"), 1), ConfigLine("expose-ro=${A:B}", Path("p.conf"), 2)]
    with pytest.raises(ConfigSyntaxError) as raised:
        substitute_config_env_vars(lines, {"HOME": "/h"})
    [error] = raised.value.errors
    assert "p.conf(2)" in error and "${A:B}" in error


def test_resolve_env_variables() -> None:
    assert resolve_env_variables("[${A}]", {"A": "val_a"}) == "[val_a]"
    # Without ref
    assert resolve_env_variables("[${Z}]", {"A": "val_a"}) == "[]"
    # Recursive variable
    assert resolve_env_variables("[${A${B}}]", {"AB": "val_ab", "B": "B"}) == "[val_ab]"
    # Break recursive variable
    assert resolve_env_variables("[${A${B}]", {"AB": "val_ab", "B": "B"}) == "[${AB]"

    assert resolve_env_variables("${A${B}}", {"B": "B"}) == ""

    # test with default value
    assert resolve_env_variables("[${A:-def}]", {"A": "val_a"}) == "[val_a]"
    assert resolve_env_variables("[${A:-def}]", {}) == "[def]"
    assert resolve_env_variables("[${A:-${B}}]", {"B": "val_b"}) == "[val_b]"

    # With recursive values
    assert (
        resolve_env_variables(
            "[${${B}:-${${D}}}]",
            {
                "A": "val_a",
                "B": "A",
                "C": "val_c",
                "D": "C",
            },
        )
        == "[val_a]"
    )

    assert (
        resolve_env_variables(
            "[${${B}:-${${D}}}]",
            {
                "A": "val_a",
                "B": "X",
                "C": "val_c",
                "D": "C",
            },
        )
        == "[val_c]"
    )


def _legacy_compile(glob: str) -> "re.Pattern[str]":
    """The regex translation `GlobPattern` replaced, kept as the equivalence oracle."""
    return re.compile(re.escape(glob).replace("\\*", ".*") + r"\Z")


def test_glob_pattern_semantics() -> None:
    """`*` spans any run of non-newline characters, and the match covers the whole subject."""
    cases: List[tuple[str, str, bool]] = [
        ("getattr", "getattr", True),
        ("getattr", "getattr_more", False),
        ("get*", "getattr", True),
        ("get*", "forget_me", False),  # anchored on the start
        ("*_KEY", "API_KEY", True),
        ("*_API_KEY", "ANY_API_KEY_AND_MORE", False),  # anchored on the end
        ("*", "", True),
        ("", "", True),
        ("", "a", False),
        ("a*b*c", "axxbyyc", True),
        ("a*b*c", "axxbyy", False),
        ("a.c", "a.c", True),
        ("a.c", "abc", False),  # regex metacharacters stay literal
        ("a+c", "a+c", True),
        ("*", "a\nb", False),  # `*` does not cross a newline
        ("a*", "a\n", False),
    ]
    for glob, subject, expected in cases:
        assert GlobPattern(glob).match(subject) is expected, f"{glob!r} vs {subject!r}"


def test_glob_pattern_matches_legacy_regex() -> None:
    """Pin the language: identical verdicts to the regex translation, newlines included."""
    rng = random.Random(987654321)
    for _ in range(20000):
        glob = "".join(rng.choice("ab*\n*") for _ in range(rng.randint(0, 8)))
        subject = "".join(rng.choice("ab\n") for _ in range(rng.randint(0, 8)))
        assert GlobPattern(glob).match(subject) is bool(
            _legacy_compile(glob).match(subject)
        ), f"glob={glob!r} subject={subject!r}"


def test_glob_pattern_does_not_backtrack() -> None:
    """The shape that made the regex translation explode must stay linear.

    `_legacy_compile("*a*a*a*a*a*a*Z*")` needs more than five seconds on this
    subject: it explores every way to split the run of `a` between the groups.
    """
    glob = "*a" * 6 + "*Z*"
    subject = "a" * 101 + "!"
    started = time.monotonic()
    assert GlobPattern(glob).match(subject) is False
    assert time.monotonic() - started < 1.0


def test_follow_links_executable_keeps_every_link_of_the_chain(tmp_path: Path) -> None:
    """Each directory the symlink chain *names* is reported, not just the one it ends on.

    Reproduces the uv venv layout: `.venv/bin/python3` points at `python`, which points
    into `cpython-3.14-linux-x86_64-gnu`, itself a symlink to the patch-level
    `cpython-3.14.5-linux-x86_64-gnu`. Resolving the chain in one jump yields only the
    latter, so a backend exposing the result still had the launcher open the former --
    and every sandbox that confines the filesystem died with `setpriv: failed to execute
    .venv/bin/python3: No such file or directory`.
    """
    real = tmp_path / "cpython-3.14.5-linux-x86_64-gnu"
    (real / "bin").mkdir(parents=True)
    (real / "bin" / "python3.14").write_text("#!/bin/false\n")
    alias = tmp_path / "cpython-3.14-linux-x86_64-gnu"
    alias.symlink_to(real)

    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    (venv_bin / "python").symlink_to(alias / "bin" / "python3.14")
    (venv_bin / "python3").symlink_to("python")

    found = follow_links_executable(venv_bin / "python3", set())

    assert alias in found, f"the intermediate link is missing: {sorted(map(str, found))}"
    assert real in found
    assert tmp_path / "venv" in found


def test_follow_links_executable_exposes_a_windows_venv_and_its_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A Windows venv keeps python.exe in Scripts\, as a copy rather than a symlink: the
    # walk exposed that one file, and neither the venv's site-packages nor the base
    # interpreter's Lib\ and DLLs\ -- so under the armed guard `import gzip` failed.
    venv_scripts = tmp_path / "venv" / "Scripts"
    venv_scripts.mkdir(parents=True)
    (venv_scripts / "python.exe").write_text("")
    base = tmp_path / "Python313"
    base.mkdir()
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr("sys.base_prefix", str(base))

    found = follow_links_executable(venv_scripts / "python.exe", set())

    assert tmp_path / "venv" in found, sorted(map(str, found))
    assert base in found, sorted(map(str, found))


def test_the_config_of_a_namespace_package_is_found(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "nspkg_for_config"
    package.mkdir()
    (package / ".py-sandboxes").write_text("learn=false\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert find_config_for_module("nspkg_for_config", ".py-sandboxes") == package / ".py-sandboxes"


@pytest.mark.parametrize(("code", "status"), [(None, 0), (0, 0), (3, 3), ("boom", 1), (["x"], 1)])
def test_exit_status_follows_cpython(code: object, status: int) -> None:
    assert exit_status(SystemExit(code)) == status


def test_exit_status_reports_a_message_only_when_asked(capsys: pytest.CaptureFixture[str]) -> None:
    assert exit_status(SystemExit("boom")) == 1
    assert capsys.readouterr().err == ""
    assert exit_status(SystemExit("boom"), report=True) == 1
    assert capsys.readouterr().err == "boom\n"
