# Copyright (c) 2026, Carbon-It, Philippe Prados (pprados)
# License: Apache V2

from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock

from pysandboxes.guard_provider import parse_rules
from pysandboxes.main_logger import ErrorMsg
from pysandboxes.sb_types import ConfigLine

# A namedtuple to mock the sb_types.Rule
Rule = namedtuple("Rule", ["rule", "path", "ln"])


# Helper to create a mock Path object
def create_mock_path(
    path_str: str, exists_val: bool = True, parent_exists_val: bool = True
) -> MagicMock:
    mock_p = MagicMock(spec=Path)
    mock_p.__str__.return_value = path_str  # type: ignore[attr-defined]
    mock_p.exists.return_value = exists_val

    mock_p.parent = MagicMock(spec=Path)
    mock_p.parent.__str__.return_value = str(Path(path_str).parent)
    mock_p.parent.exists.return_value = parent_exists_val  # Mock parent's exists

    # Mock the division operator for path joining
    mock_p.__truediv__.side_effect = lambda other: create_mock_path(
        str(Path(path_str) / other)
    )

    return mock_p


def test_parse_rules_defaults_no_config_exists(mocker: MagicMock) -> None:
    """
    Tests default values when the config file does not exist.
    'learn' should be True in this case.
    """
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=False)

    # Configure the mocked Path class to return our specific mock when called with the config path
    mock_path_class.side_effect = lambda p: (
        config_path_mock
        if str(p) == "/fake/pysandbox.conf"
        else create_mock_path(str(p))
    )

    rules: list[ConfigLine] = []
    errors: list[ErrorMsg] = []

    port, provider, use_py_sandbox, learning_path, learn, other_rules = parse_rules(
        config_path_mock, rules, errors
    )

    assert port == -1
    assert provider == "subprocess"
    assert use_py_sandbox is True
    assert learning_path == config_path_mock
    assert learn is True
    assert other_rules == []
    assert errors == []


def test_parse_rules_defaults_config_exists(mocker: MagicMock) -> None:
    """
    Tests default values when the config file exists.
    'learn' should be False.
    """
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)

    mock_path_class.side_effect = lambda p: (
        config_path_mock
        if str(p) == "/fake/pysandbox.conf"
        else create_mock_path(str(p))
    )

    rules: list[ConfigLine] = []
    errors: list[ErrorMsg] = []

    port, provider, use_py_sandbox, learning_path, learn, other_rules = parse_rules(
        config_path_mock, rules, errors
    )

    assert port == -1
    assert provider == "subprocess"
    assert use_py_sandbox is True
    assert learning_path == config_path_mock
    assert learn is False
    assert other_rules == []
    assert errors == []


def test_os_sandbox_valid(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    cli_path_mock = create_mock_path(".", exists_val=True)  # For Path('.')

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        ".": cli_path_mock,
    }.get(str(p), create_mock_path(str(p)))

    rules = [ConfigLine("os-sandbox=subprocess", cli_path_mock, 1)]
    errors: list[ErrorMsg] = []
    _, provider, _, _, _, _ = parse_rules(config_path_mock, rules, errors)
    assert provider == "subprocess"
    assert errors == []


def test_os_sandbox_invalid(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    cli_path_mock = create_mock_path(".", exists_val=True)

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        ".": cli_path_mock,
    }.get(str(p), create_mock_path(str(p)))

    rules = [ConfigLine("os-sandbox=invalid", cli_path_mock, 1)]
    errors: list[ErrorMsg] = []
    _, provider, _, _, _, _ = parse_rules(config_path_mock, rules, errors)
    assert provider == "error"
    assert len(errors) == 1
    assert "Invalid os-sandbox 'invalid'" in errors[0][0]


def test_py_sandbox_false(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    cli_path_mock = create_mock_path(".", exists_val=True)

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        ".": cli_path_mock,
    }.get(str(p), create_mock_path(str(p)))

    rules = [ConfigLine("py-sandbox=false", cli_path_mock, 1)]
    errors: list[ErrorMsg] = []
    _, _, use_py_sandbox, _, learn, _ = parse_rules(config_path_mock, rules, errors)
    assert use_py_sandbox is False
    assert learn is False
    assert errors == []


def test_py_sandbox_invalid(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    cli_path_mock = create_mock_path(".", exists_val=True)

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        ".": cli_path_mock,
    }.get(str(p), create_mock_path(str(p)))

    rules = [ConfigLine("py-sandbox=invalid", cli_path_mock, 1)]
    errors: list[ErrorMsg] = []
    _, provider, _, _, _, _ = parse_rules(config_path_mock, rules, errors)
    assert provider == "error"
    assert len(errors) == 1
    assert "Invalid value 'invalid' for py-sandbox" in errors[0][0]


def test_port_valid(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    cli_path_mock = create_mock_path(".", exists_val=True)

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        ".": cli_path_mock,
    }.get(str(p), create_mock_path(str(p)))

    rules = [ConfigLine("port=8080", cli_path_mock, 1)]
    errors: list[ErrorMsg] = []
    port, _, _, _, _, _ = parse_rules(config_path_mock, rules, errors)
    assert port == 8080
    assert not errors


def test_port_invalid(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    cli_path_mock = create_mock_path(".", exists_val=True)

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        ".": cli_path_mock,
    }.get(str(p), create_mock_path(str(p)))

    rules = [ConfigLine("port=abc", cli_path_mock, 1)]
    errors: list[ErrorMsg] = []
    port, _, _, _, _, _ = parse_rules(config_path_mock, rules, errors)
    assert port == -1
    assert len(errors) == 1
    assert "Port must be a positive value" in errors[0][0]


def test_port_negative(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    cli_path_mock = create_mock_path(".", exists_val=True)

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        ".": cli_path_mock,
    }.get(str(p), create_mock_path(str(p)))

    rules = [ConfigLine("port=-100", cli_path_mock, 1)]
    errors: list[ErrorMsg] = []
    port, _, _, _, _, _ = parse_rules(config_path_mock, rules, errors)
    assert port == -1
    assert len(errors) == 1
    assert "Port must be a positive value" in errors[0][0]


def test_learn_path(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    rule_path_mock = create_mock_path(
        "/tmp/pysandbox.conf", exists_val=True, parent_exists_val=True
    )
    learning_file_path_mock = create_mock_path(
        "/tmp/new_config.conf", exists_val=False, parent_exists_val=True
    )

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        "/tmp/pysandbox.conf": rule_path_mock,
        "new_config.conf": learning_file_path_mock,  # When Path("new_config.conf") is called
    }.get(str(p), create_mock_path(str(p)))

    rules = [ConfigLine("learn=new_config.conf", rule_path_mock, 1)]
    errors: list[ErrorMsg] = []

    _, _, _, learning_path, learn, _ = parse_rules(config_path_mock, rules, errors)

    assert str(learning_path) == str(Path("/tmp") / "new_config.conf")
    assert learn is True
    assert not errors


def test_learn_invalid_value(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    cli_path_mock = create_mock_path(".", exists_val=True)

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        ".": cli_path_mock,
    }.get(str(p), create_mock_path(str(p)))

    rules = [ConfigLine("learn=true", cli_path_mock, 1)]
    errors: list[ErrorMsg] = []
    _, provider, _, _, _, _ = parse_rules(config_path_mock, rules, errors)
    assert provider == "error"
    assert len(errors) == 1
    assert "Invalid value 'true' for 'learn'" in errors[0][0]


def test_multiple_rules(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    cli_path_mock = create_mock_path(".", exists_val=True)

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        ".": cli_path_mock,
    }.get(str(p), create_mock_path(str(p)))

    rules = [
        ConfigLine("os-sandbox=subprocess", cli_path_mock, 1),
        ConfigLine("py-sandbox=true", cli_path_mock, 2),
        ConfigLine("port=9999", cli_path_mock, 3),
        ConfigLine("unrelated=rule", cli_path_mock, 4),
    ]
    errors: list[ErrorMsg] = []
    port, provider, use_py_sandbox, _, _, other_rules = parse_rules(
        config_path_mock, rules, errors
    )
    assert port == 9999
    assert provider == "subprocess"
    assert use_py_sandbox is True
    assert len(other_rules) == 1
    assert other_rules[0].rule == "unrelated=rule"
    assert not errors


def test_multiple_values_error(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    some_path_mock = create_mock_path("/some/path/pysandbox.conf", exists_val=True)
    another_path_mock = create_mock_path(
        "/another/path/pysandbox.conf", exists_val=True
    )

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        "/some/path/pysandbox.conf": some_path_mock,
        "/another/path/pysandbox.conf": another_path_mock,
    }.get(str(p), create_mock_path(str(p)))

    rules = [
        ConfigLine("port=8080", some_path_mock, 1),
        ConfigLine("port=9090", another_path_mock, 1),
    ]
    errors: list[ErrorMsg] = []
    _, provider, _, _, _, _ = parse_rules(config_path_mock, rules, errors)
    assert provider == "error"
    assert len(errors) == 1
    assert "Multiple port parameters" in errors[0][0]


def test_command_line_priority(mocker: MagicMock) -> None:
    mock_path_class = mocker.patch("pysandboxes.guard_provider.Path", autospec=True)

    config_path_mock = create_mock_path("/fake/pysandbox.conf", exists_val=True)
    some_path_mock = create_mock_path("/some/path/pysandbox.conf", exists_val=True)
    cli_path_mock = create_mock_path(".", exists_val=True)

    mock_path_class.side_effect = lambda p: {
        "/fake/pysandbox.conf": config_path_mock,
        "/some/path/pysandbox.conf": some_path_mock,
        ".": cli_path_mock,
    }.get(str(p), create_mock_path(str(p)))

    rules = [
        ConfigLine("port=8080", some_path_mock, 1),
        ConfigLine("port=9090", cli_path_mock, 1),  # This one should be picked
    ]
    errors: list[ErrorMsg] = []
    port, _, _, _, _, _ = parse_rules(config_path_mock, rules, errors)
    assert port == 9090
    assert not errors
