from typing import List

from pysandboxes.tools import _remove_comment, resolve_env_variables


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
    assert resolve_env_variables("[${${B}:-${${D}}}]",
                                 {
                                     "A": "val_a",
                                     "B":"A",
                                     "C": "val_c",
                                     "D": "C",
                                 }) == "[val_a]"

    assert resolve_env_variables("[${${B}:-${${D}}}]",
                                 {
                                     "A": "val_a",
                                     "B":"X",
                                     "C": "val_c",
                                     "D": "C",
                                 }) == "[val_c]"
