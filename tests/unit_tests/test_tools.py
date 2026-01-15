from typing import List

from pysandboxes.tools import _remove_comment


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
        ("path='/home/user # not comment' # real comment",
         "path='/home/user # not comment'"),
        ('mixed="single \' inside" # comment', 'mixed="single \' inside"'),
        ("escaped_quote='don\\'t remove' # comment", "escaped_quote='don\\'t remove'"),
        ('no_end_quote="unclosed # should not remove',
         'no_end_quote="unclosed # should not remove'),
    ]

    for input_line, expected in test_cases:
        result: str = _remove_comment(input_line)
        assert result == expected
