"""Unit tests for learning module."""

import logging
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from pysandboxes.learning import (
    _manage_olds_file,
    add_learning_rule,
    generate_config_from_learning,
    is_learning_mode,
    set_learning_mode,
)


class TestGenerateConfigFromLearning:
    """Test cases for generate_config_from_learning function."""

    @patch("pysandboxes.guard_envs.generate_rules")
    @patch("pysandboxes.guard_files.generate_rules")
    @patch("pysandboxes.guard_import.generate_rules")
    @patch("pysandboxes.guard_socket.generate_rules")
    @patch("pysandboxes.learning._manage_olds_file")
    @patch("pysandboxes.learning.is_learning_mode")
    def test_generate_config_with_all_rules(
        self,
        mock_is_learning_mode: Mock,
        mock_manage_olds: Mock,
        mock_socket_rules: Mock,
        mock_import_rules: Mock,
        mock_file_rules: Mock,
        mock_env_rules: Mock,
    ) -> None:
        """Test config generation with all rule types."""
        # Setup mock returns

        with tempfile.TemporaryDirectory() as temp_dir:
            test_path = Path(temp_dir) / "config.conf"
            mock_env_rules.return_value = ["env:HOME", "env:PATH"]
            mock_import_rules.return_value = ["import:os", "import:sys"]
            mock_file_rules.return_value = [
                "file:read:/tmp/*",
                "file:write:/tmp/output",
            ]
            mock_socket_rules.return_value = ["socket:tcp:80", "socket:udp:53"]
            mock_manage_olds.return_value = (test_path, None)
            mock_is_learning_mode.return_value = True

            with (
                patch("pysandboxes.learning._learning_path", Path("test.conf")),
                patch("pysandboxes.learning._save_learning_done", False),
                patch("pysandboxes.eval_rules.generate_rules", return_value=["eval:dynamic"]) as mock_eval_rules,
            ):
                generate_config_from_learning()
                generated = test_path.read_text()

        assert all(
            rule in generated
            for rule in (
                "env:HOME",
                "env:PATH",
                "import:os",
                "import:sys",
                "file:read:/tmp/*",
                "file:write:/tmp/output",
                "socket:tcp:80",
                "socket:udp:53",
                "eval:dynamic",
            )
        )
        mock_env_rules.assert_called_once()
        mock_import_rules.assert_called_once()
        mock_file_rules.assert_called_once()
        mock_socket_rules.assert_called_once()
        mock_eval_rules.assert_called_once()


class TestManageOldsFile:
    """Test cases for _manage_olds_file function."""

    def test_manage_olds_file_new_file(self) -> None:
        """Test managing old files when target doesn't exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_path = Path(temp_dir) / "new_config.conf"

            result_path, old_path = _manage_olds_file(test_path)

            assert result_path == test_path
            assert old_path is None

    def test_manage_olds_file_existing_file(self) -> None:
        """Test managing old files when target already exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_path = Path(temp_dir) / "existing_config.conf"
            test_path.write_text("existing content")

            result_path, old_path = _manage_olds_file(test_path)

            assert result_path == test_path
            assert old_path is not None
            assert old_path.suffix == ".old"

    def test_manage_olds_file_skips_backups_already_taken(self) -> None:
        """Test that a backup never overwrites an earlier one."""
        with tempfile.TemporaryDirectory() as temp_dir:
            test_path = Path(temp_dir) / "existing_config.conf"
            test_path.write_text("existing content")
            Path(f"{test_path}.old").write_text("first")
            Path(f"{test_path}.old_1").write_text("second")

            _, old_path = _manage_olds_file(test_path)

            assert old_path == Path(f"{test_path}.old_2")


class TestLearningModeManagement:
    """Test cases for learning mode activation/deactivation."""

    def test_activate_learning(self) -> None:
        """Test activating learning mode."""

        with (
            patch("pysandboxes.learning._learning_path", None),
            patch("pysandboxes.learning._learning_mode", False),
        ):
            set_learning_mode(True)

            # Check that learning mode is activated
            assert is_learning_mode() is True

    def test_stop_learning_mode(self) -> None:
        """Test stopping learning mode."""
        # First activate learning
        with patch("pysandboxes.learning._learning_path", Path("test.conf")):
            set_learning_mode(False)

            # Check that learning mode is stopped
            assert is_learning_mode() is False


class TestAddLearningRule:
    """Test cases for add_learning_rule function."""

    def test_add_learning_rule_when_inactive(self) -> None:
        """Test adding a rule when learning mode is inactive."""
        test_rule = "test_rule"

        with patch("pysandboxes.learning._learning_path", None):
            with patch("pysandboxes.learning._learning") as mock_learning:
                mock_learning_set = Mock()
                mock_learning.add = mock_learning_set.add
                add_learning_rule(test_rule)

                # Rule should not be added when learning is inactive
                mock_learning_set.add.assert_not_called()

    def test_add_learning_rule_duplicate(self) -> None:
        """Adding the same learning rule twice keeps only one copy."""
        test_rule = "duplicate_rule"

        with (
            patch("pysandboxes.learning._learning_path", Path("test.conf")),
            patch("pysandboxes.learning._learning_mode", True),
            patch("pysandboxes.learning._learning", set[str]()) as learned,
        ):
            add_learning_rule(test_rule)
            add_learning_rule(test_rule)

        assert learned == {test_rule}

    def test_add_learning_rule_different_types(self) -> None:
        """Test adding different types of learning rules."""
        rules = [
            "file:/path/to/file",
            "socket:tcp:80",
            "import:code_path",
            "env:VARIABLE_NAME",
        ]

        with (
            patch("pysandboxes.learning._learning_path", Path("test.conf")),
            patch("pysandboxes.learning._learning_mode", True),
            patch("pysandboxes.learning._learning", set[str]()) as learned,
        ):
            for rule in rules:
                add_learning_rule(rule)

        assert learned == set(rules)


def _patched_rule_generators(envs: list[str] | None = None, imports: list[str] | None = None) -> tuple:
    """Patch every generate_rules a learning run calls, so only env rules vary."""
    return (
        patch("pysandboxes.guard_envs.generate_rules", return_value=envs or []),
        patch("pysandboxes.guard_import.generate_rules", return_value=imports or []),
        patch("pysandboxes.guard_files.generate_rules", return_value=[]),
        patch("pysandboxes.guard_socket.generate_rules", return_value=[]),
        patch("pysandboxes.guard_api.generate_rules", return_value=[]),
        patch("pysandboxes.eval_rules.generate_rules", return_value=[]),
    )


class TestAtomicWrite:
    """A6.1: a crash while publishing must not remove or truncate the live config."""

    def test_crash_during_write_leaves_old_content_in_place(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Fails before the fix: the old code renames the file away, then writes,
        so a write failure leaves the live config missing. After the fix, the old
        content is only copied (not moved) and the new content is published
        atomically, so a write failure leaves the original file untouched.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg = Path(temp_dir) / ".py-sandboxes"
            original = "py-sandbox=true\n# </learning_guard_envs>\n"
            cfg.write_text(original)

            def boom_fdopen(*_args: object, **_kwargs: object) -> None:
                raise OSError("boom")

            monkeypatch.setattr("pysandboxes.learning.os.fdopen", boom_fdopen)

            patches = _patched_rule_generators(["env=FOO=${FOO}"])
            with (
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patches[4],
                patches[5],
                patch("pysandboxes.learning._learning_path", cfg),
                patch("pysandboxes.learning._save_learning_done", False),
                patch("pysandboxes.learning.is_learning_mode", return_value=True),
                patch("pysandboxes.learning._learning", set()),
            ):
                with pytest.raises(OSError):
                    generate_config_from_learning()

            assert cfg.exists(), "the live config must still exist after a failed publish"
            assert cfg.read_text() == original, "the live config must keep its old content, not be truncated"


class TestBackupCollision:
    """A6.2: the `.old` backup name must not collide across different configs."""

    def test_backup_names_do_not_collide_across_different_configs(self) -> None:
        """Fails before the fix: ``with_suffix`` drops the part of the name that
        tells "myconf.py-sandboxes" and "myconf" apart, so both back up to
        "myconf.old". After the fix, the suffix is appended, keeping the full name.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_a = Path(temp_dir) / "myconf.py-sandboxes"
            cfg_a.write_text("a")
            cfg_b = Path(temp_dir) / "myconf"
            cfg_b.write_text("b")

            _, backup_a = _manage_olds_file(cfg_a)
            _, backup_b = _manage_olds_file(cfg_b)

        assert backup_a is not None
        assert backup_b is not None
        assert backup_a != backup_b, "two different configs must not back up to the same file"


class TestIdempotentRerun:
    """A6.3: rerunning on an output that already holds the learned rules must not
    duplicate them.
    """

    def test_rerunning_on_the_same_output_does_not_duplicate_rules(self) -> None:
        """Fails before the fix: a guard's ``generate_rules()`` skips a candidate only
        when the rules active for this run (loaded from ``--pysandboxes-config``)
        already allow it; it never reads what the ``--learn=<file>`` target already
        holds. Confirmed against the real CLI with ``--pysandboxes-config=A`` and
        ``--learn=B``: running twice duplicates the env rule in B while A stays
        untouched. This test mocks the generators to isolate the fix itself: a
        candidate line already present in the target file is dropped before
        insertion, so a rerun is a no-op (no new header, no backup).
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg = Path(temp_dir) / "out.py-sandboxes"

            patches = _patched_rule_generators(["env=FOO=${FOO}"])
            with (
                patches[0],
                patches[1],
                patches[2],
                patches[3],
                patches[4],
                patches[5],
                patch("pysandboxes.learning._learning_path", cfg),
                patch("pysandboxes.learning.is_learning_mode", return_value=True),
                patch("pysandboxes.learning._learning", set()),
            ):
                with patch("pysandboxes.learning._save_learning_done", False):
                    generate_config_from_learning()
                with patch("pysandboxes.learning._save_learning_done", False):
                    generate_config_from_learning()

            generated = cfg.read_text()
            backup_exists = (Path(temp_dir) / "out.py-sandboxes.old").exists()

        assert generated.count("env=FOO=${FOO}") == 1, "a no-op rerun must not duplicate learned rules"
        assert generated.count("# Add rules") == 1, "a no-op rerun must not insert a second dated header"
        assert not backup_exists, "a no-op rerun must not create a backup: nothing changed to back up"


class TestEnvVarsNeverRead:
    """A6.4: probing for the path-substitution table must not record a use."""

    def test_building_the_substitution_table_does_not_record_a_use(self) -> None:
        """Fails before the fix: ``guard_files`` builds its ``${HOME}``/``${TMPDIR}``
        substitution table with ``_learn_env.get(key)``, a tracked read, so HOME and
        PWD are learned even though the sandboxed application never reads them.
        After the fix, it uses ``_learn_env._get(key)``, which reads without
        recording a use.
        """
        script = textwrap.dedent("""
            import os
            from pysandboxes.guard_envs import LearnEnviron

            LearnEnviron._instance = None
            envs = LearnEnviron()
            os.environ = envs
            import pysandboxes.guard_files as gf  # builds the substitution table

            probed = set(gf._special_env) | set(gf._special_home)
            print(",".join(sorted(envs._keys_used)))
            print(",".join(sorted(probed)))
            """)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        used_line, probed_line = result.stdout.strip().splitlines()
        used = set(used_line.split(",")) if used_line else set()
        probed = set(probed_line.split(",")) if probed_line else set()
        assert not (used & probed), f"probing the substitution table must not record a use, but {used & probed} did"

    def test_generating_file_rules_does_not_learn_home(self) -> None:
        script = textwrap.dedent("""
            import os
            from pathlib import Path
            from pysandboxes.guard_envs import LearnEnviron
            from pysandboxes.py_sandbox import _parse_include
            from pysandboxes.sb_types import ConfigLine

            LearnEnviron._instance = None
            envs = LearnEnviron()
            os.environ = envs
            from pysandboxes.guard_files import LearnFileRule, generate_rules
            from pysandboxes.main_logger import make_relative_path

            envs._keys_used.clear()
            generate_rules({LearnFileRule(Path.cwd() / "pyproject.toml", False)})
            make_relative_path(Path("/etc/passwd"))
            _parse_include(
                Path.cwd(),
                set(),
                [ConfigLine('include "~/.config/no-such-profile"', Path("profile"), 1)],
            )
            print(",".join(sorted(envs._keys_used)))
            """)
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, result.stderr
        output = result.stdout.strip()
        learned = set(output.splitlines()[-1].split(",")) if output else set()
        assert "HOME" not in learned


class TestExposeRoGranularity:
    """A6.5 (characterization, not changed): a file read directly under a directory
    widens the grant to that whole directory, rather than to just the file. Kept as
    is and documented in ``wiki/configuration.md`` as a review-before-use warning:
    the harness has to read the script file to run it, so the script's own directory
    is already learned even when the application reads nothing else there (observed:
    a script that only reads an env variable still got ``expose-ro=`` on its whole
    directory) -- narrowing other reads in that directory would not shrink the
    profile. A kernel-backed OS provider also needs every ``sys.path`` entry, which
    includes that directory, mounted for ``os.listdir``/``os.scandir`` at replay;
    this part is reasoned from the provider code, not verified by replaying under
    one. When the working directory is unrelated to the script (for example a
    caller's cwd), the same widening is pure over-breadth with no such floor, which
    is why the profile still needs a human review. This test passes both before and
    after the other fixes: it pins the documented behavior, it is not a repro of a
    bug being fixed.
    """

    def test_a_file_read_in_a_directory_exposes_the_whole_directory(self) -> None:
        from pysandboxes.guard_files import LearnFileRule
        from pysandboxes.guard_files import generate_rules as file_generate_rules

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "readme.txt").write_text("hello")
            (root / "secret.txt").write_text("should not be exposed on its own, but is")

            rules = file_generate_rules({LearnFileRule(root / "readme.txt", False)})

        assert any(
            rule.startswith("expose-ro=") and root.name in rule for rule in rules
        ), "reading one file exposes its whole parent directory"


def test_atomic_write_never_follows_a_planted_temporary_link(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Another local user could plant `<file>.<pid>.tmp` as a link to a file of ours: the write must not follow it."""
    import os

    from pysandboxes import learning

    victim = tmp_path / "victim"
    victim.write_text("untouched")
    target = tmp_path / ".py-sandboxes"
    monkeypatch.setattr(os, "getpid", lambda: 4242)
    (tmp_path / ".py-sandboxes.4242.tmp").symlink_to(victim)

    learning._write_atomic(target, "learned=rules\n")

    assert victim.read_text() == "untouched"
    assert target.read_text() == "learned=rules\n"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp") and not p.is_symlink()] == []


def test_a_profile_is_written_and_read_in_utf8(tmp_path: Path) -> None:
    """Generated profiles carry ``⚠`` in their comments: the platform's own encoding, cp1252 on Windows, cannot
    write it, and would read a path with an accent back as another one."""
    from pysandboxes import learning
    from pysandboxes.py_sandbox import _read_config_and_remove_comments

    target = tmp_path / ".py-sandboxes"
    learning._write_atomic(target, "# ⚠ Dangerous!\nexpose-ro=/data/café\n")

    written = target.read_bytes().replace(b"\r\n", b"\n")
    assert written == "# ⚠ Dangerous!\nexpose-ro=/data/café\n".encode("utf-8")
    assert [line.rule for line in _read_config_and_remove_comments(target)] == ["expose-ro=/data/café"]


@pytest.mark.parametrize("provider", ["landlock", "subprocess"])
def test_a_generated_profile_names_the_default_provider_in_clear(tmp_path: Path, provider: str) -> None:
    cfg = tmp_path / ".py-sandboxes"
    patches = _patched_rule_generators(["env=FOO=${FOO}"])
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patch("pysandboxes.learning._learning_path", cfg),
        patch("pysandboxes.learning._save_learning_done", False),
        patch("pysandboxes.learning.is_learning_mode", return_value=True),
        patch("pysandboxes.learning._learning", set()),
        patch("pysandboxes._os_sandbox.default_os_sandbox", return_value=provider),
    ):
        generate_config_from_learning()

    text = cfg.read_text()
    assert f"os-sandbox=${{OS_SANDBOX:-{provider}}}" in text
    assert "@DEFAULT_OS_SANDBOX@" not in text


def test_a_run_without_a_rule_file_learns_under_subprocess(tmp_path: Path) -> None:
    from pysandboxes.py_sandbox import load_and_parse_config

    all_rules = load_and_parse_config(config_path=tmp_path / ".py-sandboxes")

    assert all_rules.learn
    assert all_rules.os_sandbox == "subprocess"


def _generate(
    cfg: Path,
    envs: list[str] | None = None,
    api: list[str] | None = None,
    imports: list[str] | None = None,
) -> None:
    patches = list(_patched_rule_generators(envs))
    patches[1] = patch("pysandboxes.guard_import.generate_rules", return_value=imports or [])
    patches[4] = patch("pysandboxes.guard_api.generate_rules", return_value=api or [])
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patch("pysandboxes.learning._learning_path", cfg),
        patch("pysandboxes.learning._save_learning_done", False),
        patch("pysandboxes.learning.is_learning_mode", return_value=True),
        patch("pysandboxes.learning._learning", set()),
    ):
        generate_config_from_learning()


def test_learned_rules_are_inserted_before_their_section_marker(tmp_path: Path) -> None:
    cfg = tmp_path / ".py-sandboxes"

    _generate(cfg, envs=["env=FOO=${FOO}"], api=["python-api=ALLOW:threads"])

    lines = cfg.read_text().split("\n")
    assert lines.index("env=FOO=${FOO}") < lines.index("# </learning_guard_envs>")
    assert lines.index("python-api=ALLOW:threads") < lines.index("# </learning_guard_api>")
    assert lines.index("# </learning_guard_envs>") < lines.index("python-api=ALLOW:threads")


def test_rules_without_a_marker_in_the_existing_file_are_appended(tmp_path: Path) -> None:
    cfg = tmp_path / ".py-sandboxes"
    cfg.write_text("py-sandbox=true\n")

    _generate(cfg, envs=["env=FOO=${FOO}"])

    assert cfg.read_text().split("\n").count("env=FOO=${FOO}") == 1
    assert cfg.read_text().startswith("py-sandbox=true\n")


@pytest.mark.parametrize(("existing", "mentioned"), [("learn=.py-sandboxes\n", True), ("py-sandbox=true\n", False)])
def test_the_report_tells_to_remove_the_learn_parameter_only_when_the_file_has_one(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, existing: str, mentioned: bool
) -> None:
    cfg = tmp_path / ".py-sandboxes"
    cfg.write_text(existing)

    with caplog.at_level("INFO", logger="pysandboxes"):
        _generate(cfg, envs=["env=FOO=${FOO}"])

    assert ("Remove the 'learn' parameter" in caplog.text) is mentioned


def test_the_rules_are_written_once_per_process(tmp_path: Path) -> None:
    cfg = tmp_path / ".py-sandboxes"
    patches = _patched_rule_generators(["env=FOO=${FOO}"])
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patches[4],
        patches[5],
        patch("pysandboxes.learning._learning_path", cfg),
        patch("pysandboxes.learning._save_learning_done", False),
        patch("pysandboxes.learning.is_learning_mode", return_value=True),
        patch("pysandboxes.learning._learning", set()),
    ):
        generate_config_from_learning()
        cfg.unlink()
        generate_config_from_learning()

    assert not cfg.exists()


def test_a_failed_write_reports_its_own_error_not_a_missing_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from pysandboxes import learning

    def refuse(*_args: object, **_kwargs: object) -> int:
        raise PermissionError("no write access")

    monkeypatch.setattr(os, "open", refuse)

    with pytest.raises(PermissionError, match="no write access"):
        learning._write_atomic(tmp_path / ".py-sandboxes", "x")


def test_info_summary_maps_generated_imports_to_deduplicated_stacks_without_locals(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pysandboxes import learning
    from pysandboxes.guard_import import LearnImportRule

    rule = LearnImportRule("inspect")
    config = tmp_path / ".py-sandboxes"
    secret = "must-not-appear-in-logs"
    monkeypatch.setattr(learning, "_learning_origins", {}, raising=False)

    with (
        patch("pysandboxes.guard_envs.generate_rules", return_value=[]),
        patch("pysandboxes.guard_files.generate_rules", return_value=[]),
        patch("pysandboxes.guard_socket.generate_rules", return_value=[]),
        patch("pysandboxes.guard_api.generate_rules", return_value=[]),
        patch("pysandboxes.eval_rules.generate_rules", return_value=[]),
        patch("pysandboxes.learning._learning_path", config),
        patch("pysandboxes.learning._save_learning_done", False),
        patch("pysandboxes.learning._learning_mode", True),
        patch("pysandboxes.learning._learning", set()),
    ):
        with caplog.at_level(logging.INFO, logger="Pysandboxes"):
            for _ in range(5):
                learning.add_learning_rule(rule)
            generate_config_from_learning()

    assert "python-import=inspect" in config.read_text()
    assert "python-import=inspect" in caplog.text
    assert "LearnImportRule(name='inspect')" in caplog.text
    assert "5 observations" in caplog.text
    assert "test_info_summary_maps_generated_imports" in caplog.text
    assert caplog.text.count("test_info_summary_maps_generated_imports") == 1
    assert secret not in caplog.text


def test_info_summary_traces_generated_environment_rules(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pysandboxes import learning
    from pysandboxes.guard_envs import LearnEnviron

    monkeypatch.setattr(LearnEnviron, "_instance", None)
    monkeypatch.setattr(learning, "_learning_origins", {}, raising=False)
    environ = LearnEnviron()
    config = tmp_path / ".py-sandboxes"

    with (
        patch("pysandboxes.guard_import.generate_rules", return_value=[]),
        patch("pysandboxes.guard_files.generate_rules", return_value=[]),
        patch("pysandboxes.guard_socket.generate_rules", return_value=[]),
        patch("pysandboxes.guard_api.generate_rules", return_value=[]),
        patch("pysandboxes.eval_rules.generate_rules", return_value=[]),
        patch("pysandboxes.learning._learning_path", config),
        patch("pysandboxes.learning._save_learning_done", False),
        patch("pysandboxes.learning._learning_mode", True),
        patch("pysandboxes.learning._learning", set()),
    ):
        with caplog.at_level(logging.INFO, logger="Pysandboxes"):
            environ.learn_read("PYTEST_INFO_PROVENANCE")
            generate_config_from_learning()

    assert "env=PYTEST_INFO_PROVENANCE=" + "$" + "{PYTEST_INFO_PROVENANCE}" in config.read_text()
    assert "LearnEnvRule(key='PYTEST_INFO_PROVENANCE')" in caplog.text
    assert "test_info_summary_traces_generated_environment_rules" in caplog.text


def test_stack_capture_does_not_read_the_learning_environment(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import os

    from pysandboxes import learning
    from pysandboxes.guard_envs import LearnEnviron

    environ = LearnEnviron()
    environ._keys_used.clear()
    monkeypatch.setattr(os, "environ", environ)

    with (
        patch("pysandboxes.learning._learning_mode", True),
        caplog.at_level(logging.INFO, logger="Pysandboxes"),
    ):
        learning._capture_learning_stack()

    assert not environ._keys_used


def test_stack_capture_does_not_load_source_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    import linecache

    from pysandboxes import learning

    def refuse_source_lookup(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("stack capture must not load source lines")

    with monkeypatch.context() as scoped:
        scoped.setattr(linecache, "getline", refuse_source_lookup)
        stack = learning._capture_learning_stack()

    assert any("test_stack_capture_does_not_load_source_lines" in frame for frame in stack)


def _stack_through_a_chain(tmp_path: Path, depth: int) -> tuple[str, ...]:
    """Capture the stack under `depth` distinct functions, in a thread so the frames above are fixed."""
    import importlib.util
    import threading

    from pysandboxes import learning

    source = "".join(f"def f{i}():\n    return f{i + 1}()\n\n\n" for i in range(depth - 1))
    source += f"def f{depth - 1}():\n    return capture()\n"
    path = tmp_path / f"chain{depth}.py"
    path.write_text(source)
    spec = importlib.util.spec_from_file_location(f"chain{depth}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    module.capture = learning._capture_learning_stack  # type: ignore[attr-defined]
    spec.loader.exec_module(module)
    result: list[tuple[str, ...]] = []
    thread = threading.Thread(target=lambda: result.append(module.f0()))
    thread.start()
    thread.join()
    return result[0]


def test_a_stack_of_sixteen_frames_is_kept_whole_and_a_longer_one_is_elided(tmp_path: Path) -> None:
    base = len(_stack_through_a_chain(tmp_path, 1)) - 1
    whole = _stack_through_a_chain(tmp_path, 16 - base)
    longer = _stack_through_a_chain(tmp_path, 17 - base)

    assert len(whole) == 16
    assert "..." not in whole
    assert len(longer) == 16
    assert longer[3] == "..."
    assert longer[-1].endswith("in f%d" % (16 - base))


def test_info_summary_marks_generated_rules_without_a_captured_stack(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pysandboxes import learning

    monkeypatch.setattr(learning, "_learning_origins", {}, raising=False)
    with caplog.at_level(logging.INFO, logger="Pysandboxes"):
        _generate(tmp_path / ".py-sandboxes", imports=["python-import=inspect"])

    assert "generated: python-import=inspect" in caplog.text
    assert "origin not captured at INFO: inspect" in caplog.text


def test_learning_summary_is_suppressed_below_info_level(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pysandboxes import learning

    monkeypatch.setattr(learning, "_learning_origins", {}, raising=False)
    with caplog.at_level(logging.WARNING, logger="Pysandboxes"):
        _generate(tmp_path / ".py-sandboxes", imports=["python-import=inspect"])

    assert "Learning rule provenance" not in caplog.text


def test_info_summary_groups_other_generated_rule_families_with_sources(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pysandboxes import learning
    from pysandboxes.eval_rules import LearnEvalRule
    from pysandboxes.guard_api import LearnApiRule
    from pysandboxes.guard_files import LearnFileRule
    from pysandboxes.guard_socket import Direction, Kind, LearnSocketRule

    sources = {
        LearnFileRule(tmp_path / "app.py", False),
        LearnSocketRule("connect", Kind.TCP, "example.com", 443, Direction.OUT, ()),
        LearnApiRule("os.system"),
        LearnEvalRule("eval-call", "open"),
        "remote-result-mode=objects",
    }
    generated = {
        "envs": [],
        "imports": [],
        "files": ["expose-ro=/tmp/app"],
        "sockets": ["net=ALLOW|TCP|example.com|443|OUT"],
        "api": ["python-api=ALLOW:os.system"],
        "eval": ["eval-call=open"],
    }
    monkeypatch.setattr(learning, "_learning_origins", {}, raising=False)

    with (
        patch("pysandboxes.guard_envs.generate_rules", return_value=generated["envs"]),
        patch("pysandboxes.guard_import.generate_rules", return_value=generated["imports"]),
        patch("pysandboxes.guard_files.generate_rules", return_value=generated["files"]),
        patch("pysandboxes.guard_socket.generate_rules", return_value=generated["sockets"]),
        patch("pysandboxes.guard_api.generate_rules", return_value=generated["api"]),
        patch("pysandboxes.eval_rules.generate_rules", return_value=generated["eval"]),
        patch("pysandboxes.learning._learning_path", tmp_path / ".py-sandboxes"),
        patch("pysandboxes.learning._save_learning_done", False),
        patch("pysandboxes.learning._learning_mode", True),
        patch("pysandboxes.learning._learning", set()),
    ):
        with caplog.at_level(logging.INFO, logger="Pysandboxes"):
            for source in sources:
                learning.add_learning_rule(source)
            generate_config_from_learning()

    assert "expose-ro=/tmp/app" in caplog.text
    assert "net=ALLOW|TCP|example.com|443|OUT" in caplog.text
    assert "python-api=ALLOW:os.system" in caplog.text
    assert "eval-call=open" in caplog.text
    assert "remote-result-mode=objects" in caplog.text
    assert all(repr(source) in caplog.text for source in sources)


def _summary(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    replaces: dict[str, str],
    learning: set[Any],
    origins: dict[Any, dict[tuple[str, ...], int]],
) -> str:
    from pysandboxes import learning as learning_module

    monkeypatch.setattr(learning_module, "_learning_origins", origins, raising=False)
    with caplog.at_level(logging.INFO, logger="pysandboxes"):
        learning_module._log_learning_summary(replaces, learning)
    return caplog.text


@pytest.mark.parametrize(("count", "elided"), [(8, False), (9, True)])
def test_summary_lists_at_most_eight_imports_without_an_origin(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, count: int, elided: bool
) -> None:
    names = [f"mod{index}" for index in range(count)]
    text = _summary(monkeypatch, caplog, {"learning_guard_import": "python-import=" + ",".join(names)}, set(), {})
    assert "origin not captured at INFO: mod0, mod1, mod2, mod3, mod4, mod5, mod6, mod7" in text
    assert (" more" in text) is elided


@pytest.mark.parametrize(("count", "elided"), [(8, False), (9, True)])
def test_summary_lists_at_most_eight_env_variables_without_an_origin(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, count: int, elided: bool
) -> None:
    keys = [f"VAR{index}" for index in range(count)]
    generated = "\n".join(f"env={key}=${{{key}}}" for key in keys)
    text = _summary(monkeypatch, caplog, {"learning_guard_envs": generated}, set(), {})
    assert "origin not captured at INFO: VAR0, VAR1, VAR2, VAR3, VAR4, VAR5, VAR6, VAR7" in text
    assert (" more" in text) is elided


@pytest.mark.parametrize(("count", "elided"), [(5, False), (6, True)])
def test_summary_names_five_rules_per_stack_and_counts_the_rest(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, count: int, elided: bool
) -> None:
    from pysandboxes.eval_rules import LearnEvalRule

    rules = [LearnEvalRule("eval-call", f"fn{index}") for index in range(count)]
    text = _summary(
        monkeypatch,
        caplog,
        {"learning_guard_eval": "eval-call=x"},
        set(rules),
        {rule: {("a.py:1 in f",): 1} for rule in rules},
    )
    assert (" more rules" in text) is elided
    assert text.count("observations)") == 5


@pytest.mark.parametrize(("count", "elided"), [(12, False), (13, True)])
def test_summary_shows_twelve_stacks_and_counts_the_rest(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, count: int, elided: bool
) -> None:
    from pysandboxes.eval_rules import LearnEvalRule

    rule = LearnEvalRule("eval-call", "len")
    traces: dict[tuple[str, ...], int] = {(f"a.py:{index} in f",): 1 for index in range(count)}
    text = _summary(monkeypatch, caplog, {"learning_guard_eval": "eval-call=len"}, {rule}, {rule: traces})
    assert (" more distinct stacks" in text) is elided
    assert text.count("  source: ") == 12


@pytest.mark.parametrize(("count", "elided"), [(5, False), (6, True)])
def test_summary_names_five_sources_without_a_stack_and_keeps_reading_after_one(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, count: int, elided: bool
) -> None:
    from pysandboxes.eval_rules import LearnEvalRule

    bare = [LearnEvalRule("eval-call", f"bare{index}") for index in range(count)]
    seen = LearnEvalRule("eval-call", "seen")
    text = _summary(
        monkeypatch,
        caplog,
        {"learning_guard_eval": "eval-call=x"},
        {*bare, seen},
        {seen: {("a.py:1 in f",): 2}},
    )
    assert "LearnEvalRule(key='eval-call', name='seen') (2 observations)" in text
    assert "origin not captured at INFO: " in text
    assert (" more" in text) is elided


def test_summary_marks_a_section_without_any_source(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    text = _summary(monkeypatch, caplog, {"learning_guard_api": "python-api=ALLOW:os.system"}, set(), {})
    assert "[learning_guard_api]" in text
    assert text.count("origin not captured at INFO") == 1
