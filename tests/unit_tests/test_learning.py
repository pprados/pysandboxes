"""Unit tests for learning module."""

import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
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


def _patched_rule_generators(envs: list[str] | None = None) -> tuple:
    """Patch every generate_rules a learning run calls, so only env rules vary."""
    return (
        patch("pysandboxes.guard_envs.generate_rules", return_value=envs or []),
        patch("pysandboxes.guard_import.generate_rules", return_value=[]),
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
